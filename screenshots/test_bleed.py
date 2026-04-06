"""
Visual test: take screenshots of the reader at pages 1, 5, 10, 15, 20
to check for column bleed. Serves the reader locally, opens a headed
Chromium instance at 1512x900 (Retina 2x), navigates pages, screenshots.
"""

import subprocess
import time
import signal
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

SCREENSHOTS_DIR = Path(__file__).parent
PORT = 8765
PAGES_TO_CAPTURE = [0, 4, 9, 14, 19]  # 0-indexed


def main():
    # Start local HTTP server from project root
    project_root = SCREENSHOTS_DIR.parent
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT)],
        cwd=project_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                viewport={"width": 1512, "height": 900},
                device_scale_factor=2,  # Retina
            )
            page = context.new_page()

            # Load reader
            page.goto(f"http://localhost:{PORT}/reader/")
            page.wait_for_selector(".book-card", timeout=10000)

            # Wait for library to load, then open a content-rich chapter via JS
            # Use cambridge_science_v1 (books[1]) which has 36 chapters
            page.wait_for_function("() => state.library && state.library.books.length > 1", timeout=10000)
            book_id = page.evaluate("() => state.library.books[1].id")
            ch_id = page.evaluate("() => state.library.books[1].chapters[4].id")
            page.evaluate(f"() => openChapter('{book_id}', '{ch_id}')")

            page.wait_for_selector(".reader-content p", timeout=10000)
            time.sleep(1)  # let pagination settle

            # Diagnostics: measure actual layout
            diag = page.evaluate("""() => {
                const inner = document.querySelector('.reading-pane-inner');
                const container = document.querySelector('#reader-content');
                const innerRect = inner.getBoundingClientRect();
                const containerRect = container.getBoundingClientRect();
                const style = window.getComputedStyle(container);

                // Measure actual column positions
                const els = container.querySelectorAll('p, h1, h2, h3, blockquote, li');
                const baseX = containerRect.left;
                const xSet = new Set();
                for (const el of els) {
                    xSet.add(Math.round(el.getBoundingClientRect().left - baseX));
                    if (xSet.size >= 6) break;
                }
                const colPositions = [...xSet].sort((a, b) => a - b);

                return {
                    innerWidth: innerRect.width,
                    innerHeight: innerRect.height,
                    containerWidth: containerRect.width,
                    containerScrollWidth: container.scrollWidth,
                    columnCount: style.columnCount,
                    columnGap: style.columnGap,
                    columnWidth: style.columnWidth,
                    colPositions: colPositions,
                    pageStep: state.pageStep,
                    totalPages: state.totalPages,
                };
            }""")
            print("=== Layout Diagnostics ===")
            for k, v in diag.items():
                print(f"  {k}: {v}")

            # Check: is pageStep == contentWidth + gap?
            actual_col_step = diag['colPositions'][1] - diag['colPositions'][0] if len(diag['colPositions']) > 1 else 'N/A'
            print(f"  actual colStep (from positions): {actual_col_step}")
            print(f"  expected pageStep (2*colStep): {actual_col_step * 2 if isinstance(actual_col_step, (int, float)) else 'N/A'}")
            print(f"  our pageStep: {diag['pageStep']}")
            print(f"  innerWidth + gap: {diag['innerWidth'] + 48}")

            total = diag['totalPages']
            print(f"\nTotal pages: {total}")

            # Test 1: Screenshots WITHOUT sidebar
            for pg in PAGES_TO_CAPTURE:
                if pg >= total:
                    print(f"Page {pg+1} beyond total ({total}), skipping")
                    continue

                # Use instant scroll (no animation) for accurate screenshots
                page.evaluate(f"""() => {{
                    const inner = document.querySelector('.reading-pane-inner');
                    inner.style.scrollBehavior = 'auto';
                    state.currentPage = {pg};
                    inner.scrollLeft = state.currentPage * state.pageStep;
                    updateProgress();
                    savePrefs();
                }}""")
                time.sleep(0.3)

                # Verify scrollLeft was applied correctly
                scroll_info = page.evaluate("""() => {
                    const inner = document.querySelector('.reading-pane-inner');
                    const container = document.querySelector('#reader-content');
                    return {
                        innerScrollLeft: inner.scrollLeft,
                        innerScrollWidth: inner.scrollWidth,
                        containerScrollLeft: container.scrollLeft,
                        containerScrollWidth: container.scrollWidth,
                        expectedOffset: state.currentPage * state.pageStep,
                    };
                }""")
                print(f"  Page {pg+1}: scrollLeft={scroll_info['innerScrollLeft']}, "
                      f"expected={scroll_info['expectedOffset']}, "
                      f"innerScrollWidth={scroll_info['innerScrollWidth']}, "
                      f"containerScrollWidth={scroll_info['containerScrollWidth']}")

                path = SCREENSHOTS_DIR / f"page_{pg+1:02d}.png"
                page.screenshot(path=str(path))
                print(f"  Saved {path.name}")

            # Test 2: Open sidebar and repeat
            # Sidebar has a 0.25s CSS transition; wait for transitionend + recalc
            page.evaluate("() => toggleSidebar()")
            time.sleep(0.6)

            # Diagnostics with sidebar open
            diag2 = page.evaluate("""() => {
                const inner = document.querySelector('.reading-pane-inner');
                const container = document.querySelector('#reader-content');
                const innerRect = inner.getBoundingClientRect();
                const sidebar = document.querySelector('#sidebar');
                const sidebarRect = sidebar ? sidebar.getBoundingClientRect() : null;
                return {
                    innerWidth: innerRect.width,
                    sidebarWidth: sidebarRect ? sidebarRect.width : 'hidden',
                    sidebarDisplay: sidebar ? window.getComputedStyle(sidebar).display : 'none',
                    pageStep: state.pageStep,
                    totalPages: state.totalPages,
                    containerScrollWidth: container.scrollWidth,
                };
            }""")
            print("\n=== Sidebar Open Diagnostics ===")
            for k, v in diag2.items():
                print(f"  {k}: {v}")

            for pg in [0, 4, 9]:
                if pg >= diag2['totalPages']:
                    continue
                page.evaluate(f"""() => {{
                    const inner = document.querySelector('.reading-pane-inner');
                    inner.style.scrollBehavior = 'auto';
                    state.currentPage = {pg};
                    inner.scrollLeft = state.currentPage * state.pageStep;
                    updateProgress();
                }}""")
                time.sleep(0.3)

                scroll_info = page.evaluate("""() => {
                    const inner = document.querySelector('.reading-pane-inner');
                    return {
                        scrollLeft: inner.scrollLeft,
                        expected: state.currentPage * state.pageStep,
                    };
                }""")
                print(f"  Sidebar Page {pg+1}: scrollLeft={scroll_info['scrollLeft']}, expected={scroll_info['expected']}")

                path = SCREENSHOTS_DIR / f"sidebar_page_{pg+1:02d}.png"
                page.screenshot(path=str(path))
                print(f"  Saved {path.name}")

            browser.close()
    finally:
        server.send_signal(signal.SIGTERM)
        server.wait()


if __name__ == "__main__":
    main()
