/**
 * E-book reader for Markdown chapters.
 * Vanilla JS, no build step. Depends on markdown-it and markdown-it-footnote from CDN.
 */

/* global markdownit, markdownitFootnote */

const STORAGE_KEY = 'doc2md-reader';
const FONT_MIN = 14;
const FONT_MAX = 28;
const FONT_STEP = 2;
const FONT_DEFAULT = 18;

// --- State ---

const state = {
  library: null,
  currentBook: null,
  currentChapter: null,
  currentPage: 0,
  totalPages: 1,
  fontSize: FONT_DEFAULT,
  theme: 'light',
  sidebarVisible: false,
  chapterWords: 0,
  bookWords: 0,
  wordsBeforeChapter: 0,
};

// --- Markdown Setup ---

let md;

function initMarkdown() {
  md = markdownit({ html: false, linkify: true, typographer: true });
  md.use(markdownitFootnote);
}

// --- DOM References ---

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// --- Persistence ---

function loadPrefs() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    state.fontSize = saved.fontSize ?? FONT_DEFAULT;
    state.theme = saved.theme ?? 'light';
    state.currentBook = saved.currentBook ?? null;
    state.currentChapter = saved.currentChapter ?? null;
    state.currentPage = saved.currentPage ?? 0;
  } catch { /* ignore */ }
}

function savePrefs() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    fontSize: state.fontSize,
    theme: state.theme,
    currentBook: state.currentBook,
    currentChapter: state.currentChapter,
    currentPage: state.currentPage,
  }));
}

// --- Theme ---

function applyTheme(theme) {
  state.theme = theme;
  document.documentElement.setAttribute('data-theme', theme);
  savePrefs();
}

function cycleTheme() {
  const themes = ['light', 'dark', 'sepia'];
  const idx = themes.indexOf(state.theme);
  applyTheme(themes[(idx + 1) % themes.length]);
  updateThemeButton();
}

function updateThemeButton() {
  const icons = { light: '\u2600', dark: '\u263E', sepia: '\u2615' };
  $('#btn-theme').textContent = icons[state.theme] || '\u2600';
}

// --- Font Size ---

function applyFontSize(size) {
  state.fontSize = Math.max(FONT_MIN, Math.min(FONT_MAX, size));
  document.documentElement.style.setProperty('--font-size', state.fontSize + 'px');
  savePrefs();
  if (state.currentChapter) {
    requestAnimationFrame(() => recalcPages());
  }
}

// --- Library ---

/** Base path to project root (reader/ is one level down). */
const BASE = '../';

async function loadLibrary() {
  const resp = await fetch(BASE + 'library.json');
  if (!resp.ok) throw new Error('Failed to load library.json');
  state.library = await resp.json();
}

function renderLibrary() {
  const container = $('#library-content');
  container.innerHTML = '';

  if (!state.library || !state.library.books.length) {
    container.innerHTML = '<p class="loading">No books found. Run build_library.py first.</p>';
    return;
  }

  for (const book of state.library.books) {
    const card = document.createElement('div');
    card.className = 'book-card';

    const header = document.createElement('div');
    header.className = 'book-card-header';
    header.innerHTML = `<span>${book.title}</span><span class="chapter-count">${book.chapters.length} chapters</span>`;

    const list = document.createElement('ul');
    list.className = 'chapter-list collapsed';

    header.addEventListener('click', () => {
      list.classList.toggle('collapsed');
    });

    for (const ch of book.chapters) {
      const li = document.createElement('li');
      li.className = 'chapter-item';
      li.textContent = ch.title;
      li.addEventListener('click', () => openChapter(book.id, ch.id));
      list.appendChild(li);
    }

    card.appendChild(header);
    card.appendChild(list);
    container.appendChild(card);
  }
}

// --- Navigation ---

function showLibrary() {
  state.currentBook = null;
  state.currentChapter = null;
  state.currentPage = 0;
  savePrefs();

  $('.library-view').style.display = '';
  $('.reader-view').classList.remove('active');
  $('#topbar-reader').style.display = 'none';
  $('#topbar-library').style.display = '';
}

function showReader() {
  $('.library-view').style.display = 'none';
  $('.reader-view').classList.add('active');
  $('#topbar-reader').style.display = '';
  $('#topbar-library').style.display = 'none';
}

function findBook(bookId) {
  return state.library?.books.find(b => b.id === bookId);
}

function findChapter(bookId, chapterId) {
  const book = findBook(bookId);
  return book?.chapters.find(c => c.id === chapterId);
}

async function openChapter(bookId, chapterId) {
  const chapter = findChapter(bookId, chapterId);
  if (!chapter) return;

  state.currentBook = bookId;
  state.currentChapter = chapterId;

  showReader();
  renderSidebar();
  $('#reader-content').innerHTML = '<div class="loading">Loading...</div>';

  try {
    const paths = chapter.paths || [chapter.path];
    const parts = await Promise.all(paths.map(async p => {
      const resp = await fetch(BASE + p);
      if (!resp.ok) throw new Error('Failed to load chapter');
      return resp.text();
    }));
    renderChapter(parts.join('\n\n'));

    const book = findBook(bookId);
    $('#book-title-text').textContent = book?.title || '';
    state.chapterWords = chapter.words || 0;
    state.bookWords = book?.words || 0;

    // Sum words of all chapters before the current one
    state.wordsBeforeChapter = 0;
    if (book) {
      for (const ch of book.chapters) {
        if (ch.id === chapterId) break;
        state.wordsBeforeChapter += ch.words || 0;
      }
    }

    // Restore page position if returning to same chapter
    requestAnimationFrame(() => {
      recalcPages();
      goToPage(state.currentPage);
      savePrefs();
    });
  } catch (err) {
    $('#reader-content').innerHTML = `<div class="loading">Error loading chapter: ${err.message}</div>`;
  }
}

// --- Sidebar TOC ---

function renderSidebar() {
  const book = findBook(state.currentBook);
  if (!book) return;

  const toc = $('#toc-list');
  toc.innerHTML = '';

  for (const ch of book.chapters) {
    const item = document.createElement('div');
    item.className = 'toc-item' + (ch.id === state.currentChapter ? ' active' : '');
    item.textContent = ch.title;
    item.addEventListener('click', () => {
      state.currentPage = 0;
      openChapter(state.currentBook, ch.id);
    });
    toc.appendChild(item);
  }
}

function toggleSidebar() {
  state.sidebarVisible = !state.sidebarVisible;
  const sidebar = $('#sidebar');
  sidebar.classList.toggle('hidden', !state.sidebarVisible);
  // Recalculate after the sidebar's margin-left transition completes
  // so getContentDimensions measures the final width.
  sidebar.addEventListener('transitionend', () => recalcPages(), { once: true });
}

// --- Rendering ---

function renderChapter(markdownText) {
  const html = md.render(markdownText);
  const container = $('#reader-content');
  container.innerHTML = html;
  setupFootnotePopovers(container);
}

// --- Pagination ---

function getContentDimensions() {
  const inner = $('.reading-pane-inner');
  const rect = inner.getBoundingClientRect();
  return { contentWidth: rect.width, contentHeight: rect.height };
}

const COLUMNS = 2;
const COLUMN_GAP = 48;

function recalcPages() {
  const container = $('#reader-content');
  const { contentWidth, contentHeight } = getContentDimensions();

  const inner = $('.reading-pane-inner');
  container.style.height = contentHeight + 'px';
  container.style.columnCount = COLUMNS;
  container.style.columnGap = COLUMN_GAP + 'px';
  container.style.columnWidth = 'auto';
  container.style.transform = 'none';

  // Reset scroll position and force reflow before measuring
  inner.scrollLeft = 0;
  void container.offsetHeight;

  // With column-count:2, the browser creates columns where
  // 2 * colWidth + gap = containerWidth (exact fit). The page step
  // to advance past 2 columns + the inter-page gap is containerWidth + gap.
  state.pageStep = contentWidth + COLUMN_GAP;

  state.totalPages = Math.max(1, Math.ceil(container.scrollWidth / state.pageStep));

  if (state.currentPage >= state.totalPages) {
    state.currentPage = state.totalPages - 1;
  }

  applyPageTransform(false);
  updateProgress();
}


function applyPageTransform(animate = true) {
  const inner = $('.reading-pane-inner');
  const offset = state.currentPage * state.pageStep;
  if (animate) {
    inner.style.scrollBehavior = 'smooth';
  } else {
    inner.style.scrollBehavior = 'auto';
  }
  inner.scrollLeft = offset;
}

function goToPage(page) {
  page = Math.max(0, Math.min(page, state.totalPages - 1));
  state.currentPage = page;
  applyPageTransform(true);
  updateProgress();
  savePrefs();
}

function nextPage() {
  if (state.currentPage < state.totalPages - 1) {
    goToPage(state.currentPage + 1);
  }
}

function prevPage() {
  if (state.currentPage > 0) {
    goToPage(state.currentPage - 1);
  }
}

function fmt(n) {
  return n.toLocaleString();
}

function updateProgress() {
  const chFrac = state.totalPages > 1 ? state.currentPage / (state.totalPages - 1) : 0;
  const chPct = Math.round(chFrac * 100);
  $('#progress-fill').style.width = chPct + '%';

  const chRead = Math.round(state.chapterWords * chFrac);
  const bookRead = state.wordsBeforeChapter + chRead;
  const bookPct = state.bookWords > 0 ? Math.round((bookRead / state.bookWords) * 100) : 0;

  const parts = [`Page ${state.currentPage + 1} of ${state.totalPages}`];
  if (state.chapterWords) {
    parts.push(`Ch: ${fmt(chRead)} / ${fmt(state.chapterWords)} words (${chPct}%)`);
  }
  if (state.bookWords) {
    parts.push(`Book: ${fmt(bookRead)} / ${fmt(state.bookWords)} words (${bookPct}%)`);
  }
  $('#page-info').textContent = parts.join(' · ');
}

// --- Footnote Popovers ---

function setupFootnotePopovers(container) {
  // Collect footnote definitions from the rendered HTML
  const footnoteDefs = {};
  const fnSection = container.querySelector('.footnotes, section.footnotes');
  if (fnSection) {
    const items = fnSection.querySelectorAll('li[id]');
    items.forEach(li => {
      // id is like "fn1", "fn2", etc.
      const id = li.id;
      // Clone and remove backref links
      const clone = li.cloneNode(true);
      clone.querySelectorAll('.footnote-backref').forEach(el => el.remove());
      footnoteDefs[id] = clone.innerHTML.trim();
    });
  }

  // Attach click handlers to footnote refs
  const refs = container.querySelectorAll('sup.footnote-ref a, a.footnote-ref');
  refs.forEach(ref => {
    ref.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();

      const href = ref.getAttribute('href') || '';
      // href is like "#fn1"
      const fnId = href.replace('#', '');
      const content = footnoteDefs[fnId];
      if (!content) return;

      showFootnotePopover(content, e.clientX, e.clientY);
    });
  });
}

function showFootnotePopover(html, x, y) {
  dismissPopover();

  const popover = document.createElement('div');
  popover.className = 'footnote-popover';
  popover.innerHTML = html;
  document.body.appendChild(popover);

  // Position: try below and to the right of click, adjust if off-screen
  const pad = 12;
  let left = x + pad;
  let top = y + pad;

  requestAnimationFrame(() => {
    const rect = popover.getBoundingClientRect();
    if (left + rect.width > window.innerWidth - pad) {
      left = x - rect.width - pad;
    }
    if (top + rect.height > window.innerHeight - pad) {
      top = y - rect.height - pad;
    }
    left = Math.max(pad, left);
    top = Math.max(pad, top);
    popover.style.left = left + 'px';
    popover.style.top = top + 'px';
  });

  // Dismiss on outside click
  setTimeout(() => {
    document.addEventListener('click', onDismissPopover);
  }, 0);
}

function onDismissPopover(e) {
  const popover = document.querySelector('.footnote-popover');
  if (popover && !popover.contains(e.target)) {
    dismissPopover();
  }
}

function dismissPopover() {
  document.querySelectorAll('.footnote-popover').forEach(el => el.remove());
  document.removeEventListener('click', onDismissPopover);
}

// --- Keyboard Navigation ---

function handleKeydown(e) {
  // Escape: close popover, or return to library
  if (e.key === 'Escape') {
    if (document.querySelector('.footnote-popover')) {
      dismissPopover();
    } else if (state.currentChapter) {
      showLibrary();
    }
    return;
  }

  // Only handle page turns in reader view
  if (!state.currentChapter) return;

  if (e.key === 'ArrowRight' || e.key === ' ') {
    e.preventDefault();
    nextPage();
  } else if (e.key === 'ArrowLeft') {
    e.preventDefault();
    prevPage();
  }
}

// --- Window Resize ---

let resizeTimer;
function handleResize() {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (state.currentChapter) {
      recalcPages();
      goToPage(state.currentPage);
    }
  }, 150);
}

// --- Init ---

async function init() {
  initMarkdown();
  loadPrefs();
  applyTheme(state.theme);
  applyFontSize(state.fontSize);
  updateThemeButton();

  // Wire up buttons
  $('#btn-back').addEventListener('click', showLibrary);
  $('#btn-theme').addEventListener('click', cycleTheme);
  $('#btn-theme-library').addEventListener('click', cycleTheme);
  $('#btn-font-up').addEventListener('click', () => applyFontSize(state.fontSize + FONT_STEP));
  $('#btn-font-down').addEventListener('click', () => applyFontSize(state.fontSize - FONT_STEP));
  $('#btn-toc').addEventListener('click', toggleSidebar);

  // Page turn click zones
  $('#zone-left').addEventListener('click', prevPage);
  $('#zone-right').addEventListener('click', nextPage);

  // Keyboard & resize
  document.addEventListener('keydown', handleKeydown);
  window.addEventListener('resize', handleResize);

  // Load library
  try {
    await loadLibrary();
    renderLibrary();
  } catch (err) {
    $('#library-content').innerHTML = `<p class="loading">Could not load library.json. Run: python reader/build_library.py</p>`;
  }

  // Restore reading position if available
  if (state.currentBook && state.currentChapter) {
    const chapter = findChapter(state.currentBook, state.currentChapter);
    if (chapter) {
      openChapter(state.currentBook, state.currentChapter);
      return;
    }
  }

  showLibrary();
}

document.addEventListener('DOMContentLoaded', init);
