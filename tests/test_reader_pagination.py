"""
Playwright integration tests for the e-book reader's column pagination.

Tests verify that column alignment is pixel-perfect across pages, with and
without the sidebar, at Retina resolution. Each test targets a specific bug
that occurred during development:

1. pageStep must equal contentWidth + gap (not contentWidth alone)
2. Inner container width must not be overridden by JS (circular dependency)
3. Sidebar toggle must recalculate pageStep after CSS transition completes
4. scrollLeft must match expected offset on every page (no drift)
5. No content from adjacent pages visible at column boundaries
"""

import subprocess
import signal
import sys
import time

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

PORT = 8766
COLUMN_GAP = 48
COLUMNS = 2


@pytest.fixture(scope="module")
def server():
    """Start HTTP server for the reader, shared across all tests in module."""
    project_root = str(pytest.importorskip("pathlib").Path(__file__).parent.parent)
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT)],
        cwd=project_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)
    yield proc
    proc.send_signal(signal.SIGTERM)
    proc.wait()


@pytest.fixture(scope="module")
def browser_context(server):
    """Headed Chromium at 1512x900 Retina (2x), matching production conditions."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1512, "height": 900},
            device_scale_factor=2,
        )
        yield context
        browser.close()


@pytest.fixture()
def reader_page(browser_context):
    """Load the reader with a content-rich chapter (10k+ words)."""
    page = browser_context.new_page()
    page.goto(f"http://localhost:{PORT}/reader/")
    page.wait_for_function(
        "() => state.library && state.library.books.length > 1", timeout=10000
    )
    # Open a long chapter: "Babylonian and Assyrian Astral Science" (~10k words)
    page.evaluate("""() => {
        const book = state.library.books[1];
        const ch = book.chapters[4];
        return openChapter(book.id, ch.id);
    }""")
    page.wait_for_selector(".reader-content p", timeout=10000)
    time.sleep(0.5)  # let initial pagination settle
    yield page
    page.close()


def _get_layout(page):
    """Return layout diagnostics from the reader."""
    return page.evaluate("""() => {
        const inner = document.querySelector('.reading-pane-inner');
        const container = document.querySelector('#reader-content');
        const innerRect = inner.getBoundingClientRect();

        // Measure actual column positions
        const els = container.querySelectorAll('p, h1, h2, h3, blockquote, li');
        const baseX = container.getBoundingClientRect().left;
        const xSet = new Set();
        for (const el of els) {
            xSet.add(Math.round(el.getBoundingClientRect().left - baseX));
            if (xSet.size >= 6) break;
        }

        return {
            innerWidth: innerRect.width,
            pageStep: state.pageStep,
            totalPages: state.totalPages,
            scrollWidth: container.scrollWidth,
            colPositions: [...xSet].sort((a, b) => a - b),
            innerStyleWidth: inner.style.width,
        };
    }""")


def _goto_page_instant(page, pg):
    """Navigate to a page with instant scroll and return actual scrollLeft."""
    return page.evaluate(f"""() => {{
        const inner = document.querySelector('.reading-pane-inner');
        inner.style.scrollBehavior = 'auto';
        state.currentPage = {pg};
        inner.scrollLeft = state.currentPage * state.pageStep;
        return inner.scrollLeft;
    }}""")


# --- Test 1: pageStep = contentWidth + gap ---

class TestPageStepArithmetic:
    """The original bug: pageStep = contentWidth (missing + gap)."""

    def test_page_step_equals_content_width_plus_gap(self, reader_page):
        layout = _get_layout(reader_page)
        expected = layout["innerWidth"] + COLUMN_GAP
        assert layout["pageStep"] == expected, (
            f"pageStep should be contentWidth + gap = {expected}, "
            f"got {layout['pageStep']}"
        )

    def test_page_step_equals_two_column_steps(self, reader_page):
        """pageStep must equal 2 * (colWidth + gap), derived from column positions."""
        layout = _get_layout(reader_page)
        positions = layout["colPositions"]
        assert len(positions) >= 2, "Need at least 2 column positions"
        col_step = positions[1] - positions[0]
        assert layout["pageStep"] == col_step * COLUMNS, (
            f"pageStep should be {COLUMNS} * colStep ({col_step}) = {col_step * COLUMNS}, "
            f"got {layout['pageStep']}"
        )

    def test_column_step_consistent_with_container_width(self, reader_page):
        """colStep = (containerWidth + gap) / 2, verifying CSS column-count:2 geometry."""
        layout = _get_layout(reader_page)
        positions = layout["colPositions"]
        col_step = positions[1] - positions[0]
        expected_col_step = (layout["innerWidth"] + COLUMN_GAP) / COLUMNS
        assert col_step == expected_col_step, (
            f"colStep should be (innerWidth + gap) / 2 = {expected_col_step}, "
            f"got {col_step}"
        )


# --- Test 2: No inner width override ---

class TestNoWidthOverride:
    """The circular dependency bug: setting inner width changes column layout."""

    def test_inner_width_not_set_by_js(self, reader_page):
        """JS must not set inner container width (causes circular dependency)."""
        layout = _get_layout(reader_page)
        assert layout["innerStyleWidth"] == "", (
            f"inner.style.width should be unset, got '{layout['innerStyleWidth']}'"
        )


# --- Test 3: scrollLeft alignment on every page ---

class TestScrollAlignment:
    """scrollLeft must land exactly on column boundaries, with no drift."""

    def test_scroll_left_matches_expected_on_all_pages(self, reader_page):
        layout = _get_layout(reader_page)
        total = layout["totalPages"]
        max_scroll = layout["scrollWidth"] - layout["innerWidth"]
        # Test every page (or first 25 for very long chapters)
        pages_to_test = range(min(total, 25))
        for pg in pages_to_test:
            actual = _goto_page_instant(reader_page, pg)
            # Browser clamps scrollLeft to scrollWidth - clientWidth
            expected = min(pg * layout["pageStep"], max_scroll)
            assert actual == expected, (
                f"Page {pg}: scrollLeft = {actual}, expected {expected} "
                f"(drift = {actual - expected})"
            )

    def test_no_cumulative_drift(self, reader_page):
        """Navigate to a late-but-not-last page and verify zero drift."""
        layout = _get_layout(reader_page)
        # Use second-to-last page to avoid scrollLeft clamping on the last page
        target = max(0, layout["totalPages"] - 2)
        actual = _goto_page_instant(reader_page, target)
        expected = target * layout["pageStep"]
        assert actual == expected, (
            f"Page {target}: scrollLeft = {actual}, expected {expected}, "
            f"drift = {actual - expected}"
        )


# --- Test 4: No visible content from adjacent pages ---

class TestNoBleed:
    """Column boundaries must clip exactly — no partial third column visible."""

    def test_first_element_position_on_each_page(self, reader_page):
        """The first visible element on each page must start at x=0 relative to viewport."""
        layout = _get_layout(reader_page)
        total = min(layout["totalPages"], 15)
        for pg in range(total):
            _goto_page_instant(reader_page, pg)
            # Find leftmost visible block element's position relative to inner container
            left_offset = reader_page.evaluate("""() => {
                const inner = document.querySelector('.reading-pane-inner');
                const container = document.querySelector('#reader-content');
                const innerLeft = inner.getBoundingClientRect().left;
                const els = container.querySelectorAll('p, h1, h2, h3, blockquote, li');
                let minOffset = Infinity;
                for (const el of els) {
                    const elLeft = el.getBoundingClientRect().left;
                    const offset = elLeft - innerLeft;
                    // Only elements visible within the container (0 to innerWidth)
                    if (offset >= -1 && offset < 10) {
                        minOffset = Math.min(minOffset, offset);
                    }
                }
                return minOffset;
            }""")
            assert left_offset < 2, (
                f"Page {pg}: leftmost element at x={left_offset}, "
                f"expected ~0 (content may be bleeding from previous page)"
            )

    def test_next_column_starts_beyond_visible_area(self, reader_page):
        """The next page's first column must start at least COLUMN_GAP pixels
        past the visible area's right edge, ensuring overflow:hidden clips it.

        getBoundingClientRect() reports layout positions regardless of clipping,
        so we verify the GAP between the visible boundary and the next content
        rather than checking clipped-element visibility.
        """
        layout = _get_layout(reader_page)
        inner_width = layout["innerWidth"]
        total = min(layout["totalPages"] - 1, 15)  # skip last page (no next column)
        for pg in range(total):
            _goto_page_instant(reader_page, pg)
            gap = reader_page.evaluate(f"""() => {{
                const inner = document.querySelector('.reading-pane-inner');
                const innerRect = inner.getBoundingClientRect();
                const innerRight = innerRect.right;
                const container = document.querySelector('#reader-content');
                const els = container.querySelectorAll('p, h1, h2, h3, blockquote, li');
                // Find the first element that starts past the right edge
                let minPastRight = Infinity;
                for (const el of els) {{
                    const elLeft = el.getBoundingClientRect().left;
                    if (elLeft >= innerRight) {{
                        minPastRight = Math.min(minPastRight, elLeft - innerRight);
                        break;
                    }}
                }}
                return minPastRight === Infinity ? null : minPastRight;
            }}""")
            if gap is not None:
                assert gap >= COLUMN_GAP - 1, (
                    f"Page {pg}: next column starts {gap}px past right edge, "
                    f"need >= {COLUMN_GAP}px gap for overflow:hidden to clip fully"
                )


# --- Test 5: Sidebar toggle recalculation ---

class TestSidebarRecalc:
    """pageStep must update after sidebar CSS transition completes."""

    def test_page_step_changes_when_sidebar_opens(self, reader_page):
        layout_before = _get_layout(reader_page)

        # Open sidebar and wait for transition (0.25s) + recalc
        reader_page.evaluate("() => toggleSidebar()")
        time.sleep(0.6)

        layout_after = _get_layout(reader_page)

        assert layout_after["innerWidth"] < layout_before["innerWidth"], (
            "Inner width should shrink when sidebar opens"
        )
        assert layout_after["pageStep"] < layout_before["pageStep"], (
            f"pageStep should decrease with sidebar: "
            f"before={layout_before['pageStep']}, after={layout_after['pageStep']}"
        )
        expected = layout_after["innerWidth"] + COLUMN_GAP
        assert layout_after["pageStep"] == expected, (
            f"pageStep with sidebar should be {expected}, got {layout_after['pageStep']}"
        )

    def test_no_bleed_with_sidebar_open(self, reader_page):
        """Column alignment must be correct after sidebar opens."""
        reader_page.evaluate("() => { if (!state.sidebarVisible) toggleSidebar(); }")
        time.sleep(0.6)

        layout = _get_layout(reader_page)
        # Navigate to a middle page and check scrollLeft
        pg = min(9, layout["totalPages"] - 1)
        actual = _goto_page_instant(reader_page, pg)
        expected = pg * layout["pageStep"]
        assert actual == expected, (
            f"Sidebar open, page {pg}: scrollLeft = {actual}, expected {expected}"
        )

    def test_page_step_restores_when_sidebar_closes(self, reader_page):
        """pageStep must restore after sidebar closes."""
        layout_closed = _get_layout(reader_page)

        # Open
        reader_page.evaluate("() => toggleSidebar()")
        time.sleep(0.6)
        layout_open = _get_layout(reader_page)

        # Close
        reader_page.evaluate("() => toggleSidebar()")
        time.sleep(0.6)
        layout_restored = _get_layout(reader_page)

        assert layout_restored["pageStep"] == layout_closed["pageStep"], (
            f"pageStep should restore: original={layout_closed['pageStep']}, "
            f"restored={layout_restored['pageStep']}"
        )
        assert layout_restored["pageStep"] != layout_open["pageStep"], (
            "pageStep should differ between sidebar open and closed"
        )


# --- Test 6: Smooth scroll completes ---

class TestSmoothScroll:
    """Smooth scroll must reach the target — not stop mid-animation."""

    def test_smooth_scroll_reaches_target(self, reader_page):
        """After smooth scroll with sufficient wait, scrollLeft must match target."""
        layout = _get_layout(reader_page)
        target_page = min(5, layout["totalPages"] - 1)

        reader_page.evaluate(f"() => goToPage({target_page})")
        # Smooth scroll should complete well within 2 seconds
        time.sleep(2)

        actual = reader_page.evaluate(
            "() => document.querySelector('.reading-pane-inner').scrollLeft"
        )
        expected = target_page * layout["pageStep"]
        assert actual == expected, (
            f"Smooth scroll to page {target_page}: scrollLeft = {actual}, "
            f"expected {expected} (animation may not have completed)"
        )
