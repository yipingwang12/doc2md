"""
Playwright integration tests for the reader's text-reveal playback feature.

Verifies that page-mode playback correctly reveals words across page turns
instead of cascading rapidly through all pages (the bug where no text
appears after the first page turn).
"""

import subprocess
import signal
import sys
import time
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

PORT = 8767


@pytest.fixture(scope="module")
def server():
    """Start HTTP server for the reader."""
    project_root = str(Path(__file__).parent.parent)
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
    """Headless Chromium at 1512x900."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1512, "height": 900},
            device_scale_factor=2,
        )
        yield context
        browser.close()


@pytest.fixture()
def reader_page(browser_context):
    """Load the reader with a long chapter."""
    page = browser_context.new_page()
    page.goto(f"http://localhost:{PORT}/reader/")
    page.wait_for_function(
        "() => state.library && state.library.books.length > 1", timeout=10000
    )
    # Open a long chapter to guarantee multiple pages
    page.evaluate("""() => {
        const book = state.library.books[1];
        const ch = book.chapters[4];
        return openChapter(book.id, ch.id);
    }""")
    page.wait_for_selector(".reader-content p", timeout=10000)
    time.sleep(0.5)
    yield page
    page.close()


def _playback_snapshot(page):
    """Return playback state + counts of revealed words on the current page."""
    return page.evaluate("""() => {
        const inner = document.querySelector('.reading-pane-inner');
        const innerRect = inner.getBoundingClientRect();
        const words = document.querySelectorAll('#reader-content .word');
        let visibleTotal = 0;
        let visibleRevealed = 0;
        let totalRevealed = 0;
        let firstRevealedIdx = -1;
        let lastRevealedIdx = -1;
        for (let i = 0; i < words.length; i++) {
            const w = words[i];
            const isRevealed = w.classList.contains('revealed');
            if (isRevealed) {
                totalRevealed++;
                if (firstRevealedIdx === -1) firstRevealedIdx = i;
                lastRevealedIdx = i;
            }
            const r = w.getBoundingClientRect();
            const cx = (r.left + r.right) / 2;
            if (cx >= innerRect.left && cx <= innerRect.right &&
                r.top < innerRect.bottom && r.bottom > innerRect.top) {
                visibleTotal++;
                if (isRevealed) visibleRevealed++;
            }
        }
        return {
            currentPage: state.currentPage,
            totalPages: state.totalPages,
            playbackActive: playback.active,
            playbackPlaying: playback.playing,
            playbackIndex: playback.index,
            totalWords: words.length,
            visibleTotal,
            visibleRevealed,
            totalRevealed,
            firstRevealedIdx,
            lastRevealedIdx,
            scrollLeft: inner.scrollLeft,
            pageStep: state.pageStep,
        };
    }""")


def _start_playback(page):
    page.evaluate("() => startPlayback()")


def _set_playback_speed(page, speed):
    page.evaluate(f"() => setPlaybackSpeed({speed})")


def _force_speed(page, speed):
    """Set playback speed directly, bypassing the menu's allowed values.
    Used in tests to push reveal rate fast enough for meaningful page turns."""
    page.evaluate(f"() => {{ state.playbackSpeed = {speed}; }}")


class TestPlaybackPageTurn:
    """After the first page turn in page mode, the new page must continue
    revealing words — not stay blank due to a cascade of page turns."""

    def test_playback_enters_page_mode(self, reader_page):
        """Sanity: playback starts and wraps words."""
        snap0 = _playback_snapshot(reader_page)
        assert snap0["currentPage"] == 0
        assert snap0["totalPages"] >= 3, "Need a multi-page chapter for this test"

        _start_playback(reader_page)
        time.sleep(0.3)
        snap = _playback_snapshot(reader_page)
        assert snap["playbackActive"] is True
        assert snap["totalWords"] > 100
        reader_page.evaluate("() => exitPlayback()")

    def test_page_advances_not_cascaded(self, reader_page):
        """Run playback at high speed, verify page doesn't rapidly cascade
        to the end — we should still be near the start after a short time."""
        _set_playback_speed(reader_page, 4)
        _start_playback(reader_page)

        # At 4x, ~880 WPM ≈ 68ms per word. In 4 seconds we'd reveal ~60 words,
        # which is typically < 1 page. Without the cooldown fix, the cascade
        # would push currentPage to totalPages-1 within a few hundred ms.
        time.sleep(4)

        snap = _playback_snapshot(reader_page)
        total = snap["totalPages"]
        # We should have advanced at most a couple of pages
        assert snap["currentPage"] < min(4, total - 1), (
            f"Page cascaded to {snap['currentPage']} of {total} — "
            f"cooldown not preventing rapid advances"
        )
        reader_page.evaluate("() => exitPlayback()")

    def test_words_visible_on_new_page_after_turn(self, reader_page):
        """The decisive test: after the first page turn during playback,
        the newly-visible page should have some revealed words — not be blank.
        Forces a very high reveal rate so page turns happen quickly."""
        _start_playback(reader_page)
        _force_speed(reader_page, 30)

        # Wait until we've turned at least one page
        deadline = time.time() + 20
        turned = False
        while time.time() < deadline:
            snap = _playback_snapshot(reader_page)
            if snap["currentPage"] >= 1:
                turned = True
                break
            time.sleep(0.2)
        assert turned, (
            f"Playback never advanced past page 0 "
            f"(index={snap['playbackIndex']}/{snap['totalWords']})"
        )

        # Let the scroll settle and more words reveal on the new page
        time.sleep(1.5)

        snap = _playback_snapshot(reader_page)
        assert snap["visibleTotal"] > 0, "No words on the current page"
        assert snap["visibleRevealed"] > 0, (
            f"After page turn (now on page {snap['currentPage']}/{snap['totalPages']}), "
            f"{snap['visibleTotal']} words visible but 0 revealed. "
            f"Total revealed={snap['totalRevealed']} "
            f"(idx range {snap['firstRevealedIdx']}..{snap['lastRevealedIdx']}), "
            f"playback.index={snap['playbackIndex']}, "
            f"scrollLeft={snap['scrollLeft']}, pageStep={snap['pageStep']}"
        )
        reader_page.evaluate("() => exitPlayback()")

    def test_multiple_page_turns(self, reader_page):
        """Across several turns, each page should end up with revealed words."""
        _start_playback(reader_page)
        _force_speed(reader_page, 30)

        seen_pages_with_reveals = set()
        deadline = time.time() + 60
        while time.time() < deadline:
            snap = _playback_snapshot(reader_page)
            if snap["visibleRevealed"] > 0:
                seen_pages_with_reveals.add(snap["currentPage"])
            if len(seen_pages_with_reveals) >= 3:
                break
            time.sleep(0.3)

        assert len(seen_pages_with_reveals) >= 3, (
            f"Only saw reveals on pages {sorted(seen_pages_with_reveals)}; "
            f"expected at least 3 distinct pages"
        )
        reader_page.evaluate("() => exitPlayback()")
