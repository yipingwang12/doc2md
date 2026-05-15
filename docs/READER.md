# E-Book Reader

Built-in web-based Markdown reader at `reader/`. No build step — vanilla JS + CSS, served via embedded `http.server` in the PyWebView desktop app. Paginated two-column layout inspired by Libby/Kindle.
See [PRD.md](../PRD.md) for pipeline overview.

## Current features

- **Two-column paginated reading** (CSS multi-column layout with scrollLeft page turns)
- **Library view** — browse all books/chapters from `library.json`
- **Chapter navigation** — collapsible sidebar TOC
- **Themes** — light/dark/sepia (CSS custom properties)
- **Font size control** — 14-28px range, persisted
- **Footnote popovers** — click `[^N]` to see footnote without leaving page
- **Reading position persistence** — localStorage saves book/chapter/page
- **Progress bar** — page count, chapter word count + percentage, book word count
- **Keyboard navigation** — arrow keys, space, escape
- **`build_library.py`** — scans results/ and generates library.json with word counts; deduplicates section dividers by content hash; skips metadata dirs; extracts titles from `###` headings with multiline continuation; supports multi-file chapters (front matter + content)
- **Paper header** — YAML front matter stripped before rendering; title/authors/journal·year shown above chapter content
- **Citation hover popovers** — inline `[N]` references resolved against rendered `<ol>` reference list; hover shows citation text in popover
- **Figure click modals** — "Figure N" / "Fig. N" text references matched against `figures.json`; click opens fullscreen overlay with high-res figure image and caption
- **Papers in library** — `results/papers/` treated as a book; paper YAML metadata (title, authors, journal, year) included in library.json and displayed in reader

## Usage

```bash
python reader/build_library.py   # generate library.json
doc2md-reader                    # launch desktop app (PyWebView)
# or: python src/doc2md/desktop.py
# or for dev: python -m http.server 8000 → http://localhost:8000/reader/
```

## Future reader enhancements

- Full-text search across chapters
- Bookmarks and highlights (Web Selection API)
- Font family selector (serif/sans-serif/dyslexia-friendly)
- Line spacing and margin controls
- "Time left in chapter" estimate
- Offline support (Service Worker)
- ~~Desktop app wrapper~~ ✅ `doc2md-reader` — PyWebView desktop app (py2app alias bundle in `dist/`)

## Tech stack

| Component | Choice |
|---|---|
| Markdown→HTML | markdown-it + markdown-it-footnote (vendored in `reader/vendor/`) |
| Pagination | CSS multi-column layout + scrollLeft |
| Framework | Vanilla JS (~450 lines) |
| Themes | CSS custom properties |
| Serving | PyWebView + embedded `http.server` (desktop); `python -m http.server` (dev) |
| Desktop bundle | py2app alias mode — `dist/doc2md Reader.app` (~228 KB, symlinks into venv) |

## Column bleed: diagnosis and solution

The two-column paginated reader suffered from text from adjacent pages bleeding into the visible area. This section documents the problem, failed approaches, and the working solution.

### The problem

With CSS multi-column layout, content flows into columns that extend horizontally. To show one "page" (2 columns), the reader must shift the content and clip everything outside the visible area. Text from the next or previous page's columns bled into view, getting worse on later pages due to cumulative alignment drift.

### Root cause

With `column-count: 2` and gap `G`, the browser creates columns of width `(W - G) / 2` within container width `W`. Two columns plus one gap fill the container exactly: `2 * colWidth + G = W`. But the page step — the distance between consecutive page starts — is `W + G`, not `W`. The extra `G` is the inter-page gap between the last column of one page and the first column of the next.

The original code used `pageStep = contentWidth` (missing `+ gap`), causing 48px undershoot per page turn, accumulating across pages. A subsequent fix attempt introduced DOM measurement of column positions (`_measureColumnStep()`) and set the inner container width to the measured `pageStep`. This created a circular dependency: setting the width changed the column layout, invalidating the measurement. Example at 1512px viewport: natural container width 1416px → measured colStep 732 → set inner width to 1464 → browser recalculates colWidth to 708 → actual colStep becomes 756 → 48px drift per page.

### Failed approaches

1. **`translateX` + `overflow: hidden`** — `overflow: hidden` clips at the border/padding edge, not the content edge. Translated content that extends past the left edge of the container remains visible within the padding area. Sub-pixel rendering also causes bleed at the right edge.

2. **`clip-path: inset(0)`** — clips to the same boundary as `overflow: hidden`. Does not help.

3. **`pageStep = contentWidth`** — missing `+ gap`. Drifts by one gap width (48px) per page turn.

4. **Reducing column width by 1px** — reduces but doesn't eliminate; drift still accumulates.

5. **DOM measurement + inner width override** — `_measureColumnStep()` measured actual column positions, then set `inner.style.width = pageStep`. The width change triggers a reflow that changes column widths, invalidating the measurement. Same 48px drift, different cause.

6. **Sidebar recalc via `requestAnimationFrame`** — sidebar slides in/out via CSS `margin-left` transition (0.25s). `recalcPages()` in a `requestAnimationFrame` fires before the transition completes, measuring the old width.

### Working solution

1. **`scrollLeft` instead of `translateX`** — browser's native scroll clipping is pixel-perfect. `inner.scrollLeft = offset` clips exactly at the scroll boundary.

2. **`pageStep = contentWidth + COLUMN_GAP`** — correct arithmetic. No DOM measurement, no container width override, no circular dependency. With `column-count: 2`, the browser fills the container exactly, so no partial third column can ever be visible.

3. **`clip-path: inset(0 1px 0 0)`** — 1px right-edge safety margin for sub-pixel Retina rounding.

4. **Sidebar: `transitionend` listener** — `recalcPages()` fires only after the sidebar's CSS transition completes, ensuring the width measurement reflects the final layout.

### Code pattern

```js
// pageStep = container width + inter-page gap. No measurement needed.
state.pageStep = contentWidth + COLUMN_GAP;

// Navigate via scrollLeft (not translateX)
inner.scrollLeft = currentPage * state.pageStep;
```

### Testing

Playwright visual tests (`screenshots/test_bleed.py`) verify column alignment across pages 1–15, with and without sidebar, at 1512×900 Retina (2x). Use instant scroll (`scrollBehavior: 'auto'`) for accurate screenshots — smooth scroll animation causes false positives.

## Design references

- [Libby architecture](https://rakuten.today/tech-innovation/meet-libby-overdrives-new-ereading-app.html) — augmented hybrid app, CSS column pagination
- [epub.js](https://github.com/futurepress/epub.js/) — CSS column pagination reference
- [CSS Multi-Column Book Layout](https://www.w3tutorials.net/blog/css-multi-column-multi-page-layout-like-an-open-book/)
