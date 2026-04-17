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
  mode: 'page',         // 'page' or 'scroll'
  scrollFraction: 0,    // 0..1, scroll position for scroll mode
  playbackSpeed: 1,     // 0.5..4
  fadeEnabled: true,    // word fade transition on/off
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
    state.mode = saved.mode ?? 'page';
    state.scrollFraction = saved.scrollFraction ?? 0;
    state.playbackSpeed = saved.playbackSpeed ?? 1;
    state.fadeEnabled = saved.fadeEnabled ?? true;
  } catch { /* ignore */ }
}

function savePrefs() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    fontSize: state.fontSize,
    theme: state.theme,
    currentBook: state.currentBook,
    currentChapter: state.currentChapter,
    currentPage: state.currentPage,
    mode: state.mode,
    scrollFraction: state.scrollFraction,
    playbackSpeed: state.playbackSpeed,
    fadeEnabled: state.fadeEnabled,
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
    requestAnimationFrame(() => {
      recalcPages();
      if (state.mode === 'scroll') {
        applyScrollPosition(state.scrollFraction);
      }
    });
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

    // Derive figures.json path from chapter path (same directory)
    const chapterPath = chapter.path;
    const lastSlash = chapterPath.lastIndexOf('/');
    const chapterDir = lastSlash >= 0 ? chapterPath.slice(0, lastSlash) : '';
    let figuresData = null;
    try {
      const figResp = await fetch(BASE + (chapterDir ? chapterDir + '/' : '') + 'figures.json');
      if (figResp.ok) figuresData = await figResp.json();
    } catch { /* figures.json optional */ }

    renderChapter(parts.join('\n\n'), figuresData, chapterDir);

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

    // Restore position if returning to same chapter
    requestAnimationFrame(() => {
      recalcPages();
      if (state.mode === 'scroll') {
        applyScrollPosition(state.scrollFraction);
      } else {
        goToPage(state.currentPage);
      }
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
      state.scrollFraction = 0;
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

// --- YAML Front Matter ---

function parseYamlFrontMatter(text) {
  const lines = text.split('\n');
  if (!lines.length || lines[0].trim() !== '---') return { meta: {}, body: text };
  let endIdx = null;
  for (let i = 1; i < lines.length; i++) {
    if (lines[i].trim() === '---') { endIdx = i; break; }
  }
  if (endIdx === null) return { meta: {}, body: text };

  const meta = {};
  let currentKey = null;
  for (let i = 1; i < endIdx; i++) {
    const line = lines[i];
    if (line.startsWith('  - ')) {
      if (currentKey !== null) {
        if (!Array.isArray(meta[currentKey])) meta[currentKey] = [];
        meta[currentKey].push(line.slice(4).trim());
      }
    } else if (line.includes(':')) {
      const colon = line.indexOf(':');
      const key = line.slice(0, colon).trim();
      const val = line.slice(colon + 1).trim();
      currentKey = key;
      meta[key] = val || [];
    }
  }
  const body = lines.slice(endIdx + 1).join('\n');
  return { meta, body };
}

function buildPaperMetaHtml(meta) {
  const parts = [];
  const title = meta.title;
  const authors = meta.authors;
  const journal = meta.journal;
  const year = meta.year;
  if (!title && !authors && !journal && !year) return '';
  if (title && title !== 'Unknown') {
    parts.push(`<div class="paper-meta-title">${title}</div>`);
  }
  if (authors) {
    const authorStr = Array.isArray(authors) ? authors.join('; ') : authors;
    if (authorStr) parts.push(`<div class="paper-meta-authors">${authorStr}</div>`);
  }
  if (journal || year) {
    const jy = [journal, year].filter(Boolean).join(' \u00B7 ');
    parts.push(`<div class="paper-meta-journal">${jy}</div>`);
  }
  return parts.length ? `<div class="paper-meta">${parts.join('')}</div>` : '';
}

function renderChapter(markdownText, figuresData, chapterDir) {
  // New content invalidates any in-progress playback
  if (playback.active) {
    pausePlayback();
    playback.words = [];
    playback.index = 0;
    playback.active = false;
    document.body.classList.remove('playback-active');
    updatePlaybackButtons();
  }
  const { meta, body } = parseYamlFrontMatter(markdownText);
  const paperMetaHtml = buildPaperMetaHtml(meta);
  const html = paperMetaHtml + md.render(body);
  const container = $('#reader-content');
  container.innerHTML = html;
  setupFootnotePopovers(container);
  setupCitationPopovers(container);
  setupFigurePopovers(container, figuresData || null, chapterDir || '');
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
  const inner = $('.reading-pane-inner');

  if (state.mode === 'scroll') {
    // Clear any column layout artifacts from previous page mode
    container.style.height = '';
    container.style.columnCount = '';
    container.style.columnGap = '';
    container.style.columnWidth = '';
    container.style.transform = '';
    inner.scrollLeft = 0;
    updateProgress();
    return;
  }

  const { contentWidth, contentHeight } = getContentDimensions();
  container.style.height = contentHeight + 'px';
  container.style.columnCount = COLUMNS;
  container.style.columnGap = COLUMN_GAP + 'px';
  container.style.columnWidth = 'auto';
  container.style.transform = 'none';

  // Reset scroll position and force reflow before measuring
  inner.scrollLeft = 0;
  inner.scrollTop = 0;
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

// --- Scroll Mode ---

function applyScrollPosition(fraction) {
  const inner = $('.reading-pane-inner');
  const max = inner.scrollHeight - inner.clientHeight;
  inner.scrollTop = Math.max(0, max * fraction);
}

function onScrollModeScroll() {
  const inner = $('.reading-pane-inner');
  const max = inner.scrollHeight - inner.clientHeight;
  state.scrollFraction = max > 0 ? inner.scrollTop / max : 0;
  updateProgress();
  savePrefsThrottled();
}

let savePrefsTimer;
function savePrefsThrottled() {
  clearTimeout(savePrefsTimer);
  savePrefsTimer = setTimeout(savePrefs, 250);
}

function toggleMode() {
  // Column layout changes invalidate word positions; exit playback first
  if (playback.active) exitPlayback();
  state.mode = state.mode === 'page' ? 'scroll' : 'page';
  $('.reader-view').classList.toggle('scroll-mode', state.mode === 'scroll');
  updateModeButton();
  savePrefs();
  if (state.currentChapter) {
    requestAnimationFrame(() => {
      recalcPages();
      if (state.mode === 'scroll') {
        applyScrollPosition(state.scrollFraction);
      } else {
        goToPage(state.currentPage);
      }
    });
  }
}

function updateModeButton() {
  const btn = $('#btn-mode');
  if (!btn) return;
  // Show icon representing the mode to switch *to*:
  // \u25A4 = square with horizontal fill (page), \u21C5 = up-down arrow (scroll)
  btn.textContent = state.mode === 'scroll' ? '\u25A4' : '\u21C5';
  btn.title = state.mode === 'scroll'
    ? 'Switch to page mode'
    : 'Switch to scroll mode';
}

function fmt(n) {
  return n.toLocaleString();
}

function updateProgress() {
  let chFrac;
  let positionLabel;
  if (state.mode === 'scroll') {
    chFrac = state.scrollFraction;
    positionLabel = `${Math.round(chFrac * 100)}% of chapter`;
  } else {
    chFrac = state.totalPages > 1 ? state.currentPage / (state.totalPages - 1) : 0;
    positionLabel = `Page ${state.currentPage + 1} of ${state.totalPages}`;
  }
  const chPct = Math.round(chFrac * 100);
  $('#progress-fill').style.width = chPct + '%';

  const chRead = Math.round(state.chapterWords * chFrac);
  const bookRead = state.wordsBeforeChapter + chRead;
  const bookPct = state.bookWords > 0 ? Math.round((bookRead / state.bookWords) * 100) : 0;

  const parts = [positionLabel];
  if (state.chapterWords) {
    parts.push(`Ch: ${fmt(chRead)} / ${fmt(state.chapterWords)} words (${chPct}%)`);
  }
  if (state.bookWords) {
    parts.push(`Book: ${fmt(bookRead)} / ${fmt(state.bookWords)} words (${bookPct}%)`);
  }
  $('#page-info').textContent = parts.join(' · ');
}

// --- Playback (text reveal) ---

const PLAYBACK_WPM = 220;
const WORD_INTERVAL_MS = 60000 / PLAYBACK_WPM;
const BASE_FADE_MS = 800;  // fade duration at 1x speed

const playback = {
  active: false,
  playing: false,
  words: [],
  index: 0,
  timer: null,
  lastAdvanceTime: 0,
};

const ADVANCE_COOLDOWN_MS = 550;

function wrapWordsForPlayback() {
  const container = $('#reader-content');
  const walker = document.createTreeWalker(
    container,
    NodeFilter.SHOW_TEXT,
    {
      acceptNode(node) {
        if (!node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        // Skip text inside hidden footnote sections
        let p = node.parentElement;
        while (p && p !== container) {
          if (p.classList && p.classList.contains('footnotes')) {
            return NodeFilter.FILTER_REJECT;
          }
          if (p.tagName === 'SECTION' && p.classList && p.classList.contains('footnotes')) {
            return NodeFilter.FILTER_REJECT;
          }
          p = p.parentElement;
        }
        return NodeFilter.FILTER_ACCEPT;
      },
    },
  );

  const textNodes = [];
  let node;
  while ((node = walker.nextNode())) textNodes.push(node);

  const words = [];
  for (const textNode of textNodes) {
    const parent = textNode.parentNode;
    const parts = textNode.nodeValue.split(/(\s+)/);
    const frag = document.createDocumentFragment();
    for (const part of parts) {
      if (!part) continue;
      if (/^\s+$/.test(part)) {
        frag.appendChild(document.createTextNode(part));
      } else {
        const span = document.createElement('span');
        span.className = 'word';
        span.textContent = part;
        frag.appendChild(span);
        words.push(span);
      }
    }
    parent.replaceChild(frag, textNode);
  }
  return words;
}

function unwrapWords() {
  const container = $('#reader-content');
  const spans = container.querySelectorAll('.word');
  spans.forEach(span => {
    const text = document.createTextNode(span.textContent);
    span.parentNode.replaceChild(text, span);
  });
  container.normalize();
}

function findFirstVisibleWordIndex() {
  if (!playback.words.length) return 0;
  const inner = $('.reading-pane-inner');
  const innerRect = inner.getBoundingClientRect();
  for (let i = 0; i < playback.words.length; i++) {
    const rect = playback.words[i].getBoundingClientRect();
    if (state.mode === 'scroll') {
      if (rect.bottom > innerRect.top + 4) return i;
    } else {
      if (rect.right > innerRect.left + 4 && rect.bottom > innerRect.top + 4) return i;
    }
  }
  return Math.max(0, playback.words.length - 1);
}

function enterPlayback() {
  if (playback.active) return;
  playback.words = wrapWordsForPlayback();
  if (!playback.words.length) return;
  playback.active = true;
  document.body.classList.add('playback-active');
  playback.index = findFirstVisibleWordIndex();
  for (let i = 0; i < playback.index; i++) {
    playback.words[i].classList.add('revealed');
  }
}

function exitPlayback() {
  if (!playback.active) return;
  pausePlayback();
  unwrapWords();
  playback.active = false;
  playback.words = [];
  playback.index = 0;
  document.body.classList.remove('playback-active');
  updatePlaybackButtons();
}

function startPlayback() {
  if (!playback.active) enterPlayback();
  if (!playback.active) return;
  if (playback.playing) return;
  if (playback.index >= playback.words.length) playback.index = 0;
  playback.playing = true;
  updatePlaybackButtons();
  scheduleNextWord();
}

function pausePlayback() {
  playback.playing = false;
  if (playback.timer) {
    clearTimeout(playback.timer);
    playback.timer = null;
  }
  updatePlaybackButtons();
}

function togglePlayback() {
  if (playback.playing) pausePlayback();
  else startPlayback();
}

function restartPlayback() {
  if (!state.currentChapter) return;
  if (!playback.active) enterPlayback();
  if (!playback.active) return;
  pausePlayback();
  playback.words.forEach(w => w.classList.remove('revealed'));
  playback.index = 0;
  if (state.mode === 'scroll') {
    const inner = $('.reading-pane-inner');
    inner.scrollTo({ top: 0, behavior: 'smooth' });
    state.scrollFraction = 0;
  } else {
    goToPage(0);
  }
  setTimeout(startPlayback, 450);
}

function scheduleNextWord() {
  if (!playback.playing) return;
  if (playback.index >= playback.words.length) {
    pausePlayback();
    return;
  }
  const word = playback.words[playback.index];
  word.classList.add('revealed');
  maybeAdvanceView(word);
  playback.index++;
  const interval = WORD_INTERVAL_MS / state.playbackSpeed;
  playback.timer = setTimeout(scheduleNextWord, interval);
}

function maybeAdvanceView(word) {
  // Cooldown prevents cascading advances while a smooth scroll/page turn
  // is still in progress. Without this, rect positions reflect the
  // mid-transition state and trigger further advances on every tick.
  const now = performance.now();
  if (now - playback.lastAdvanceTime < ADVANCE_COOLDOWN_MS) return;

  const inner = $('.reading-pane-inner');
  const innerRect = inner.getBoundingClientRect();

  if (state.mode === 'scroll') {
    // Keep the active word above the bottom 30% of the pane
    const rect = word.getBoundingClientRect();
    const threshold = innerRect.bottom - innerRect.height * 0.3;
    if (rect.bottom > threshold) {
      playback.lastAdvanceTime = now;
      const scrollAmount = innerRect.height * 0.35;
      inner.scrollBy({ top: scrollAmount, behavior: 'smooth' });
    }
    return;
  }

  // Page mode: look at the NEXT word. If it sits past the current page's
  // right edge (i.e. lives in the next column group), the current word was
  // the last one on this page and we should advance. Checking only the
  // current word's rect would trigger for line-ending words inside column 2,
  // causing premature page turns with many words still unrevealed on this page.
  const nextWord = playback.words[playback.index + 1];
  if (!nextWord) return;
  const nextRect = nextWord.getBoundingClientRect();
  if (nextRect.left >= innerRect.right &&
      state.currentPage < state.totalPages - 1) {
    playback.lastAdvanceTime = now;
    nextPage();
  }
}

function updatePlaybackButtons() {
  const playBtn = $('#btn-play');
  if (!playBtn) return;
  playBtn.textContent = playback.playing ? '\u23F8' : '\u25B6';
  playBtn.title = playback.playing ? 'Pause playback' : 'Start playback';
}

function formatSpeed(s) {
  return (Number.isInteger(s) ? s.toString() : s.toString()) + '\u00D7';
}

function updateSpeedButton() {
  const btn = $('#btn-speed');
  if (!btn) return;
  btn.textContent = formatSpeed(state.playbackSpeed);
  $$('#speed-menu .speed-option').forEach(opt => {
    const val = parseFloat(opt.dataset.speed);
    opt.classList.toggle('active', val === state.playbackSpeed);
  });
}

function applyFadeDuration() {
  const ms = state.fadeEnabled ? BASE_FADE_MS / state.playbackSpeed : 0;
  document.documentElement.style.setProperty('--word-fade-duration', ms + 'ms');
}

function setPlaybackSpeed(speed) {
  state.playbackSpeed = speed;
  savePrefs();
  updateSpeedButton();
  applyFadeDuration();
  // If currently playing, restart the timer so the new interval takes effect
  if (playback.playing && playback.timer) {
    clearTimeout(playback.timer);
    const interval = WORD_INTERVAL_MS / state.playbackSpeed;
    playback.timer = setTimeout(scheduleNextWord, interval);
  }
}

function setFadeEnabled(enabled) {
  state.fadeEnabled = enabled;
  savePrefs();
  updateFadeToggle();
  applyFadeDuration();
}

function toggleFade() {
  setFadeEnabled(!state.fadeEnabled);
}

function updateFadeToggle() {
  const btn = $('#btn-fade-toggle');
  if (btn) btn.classList.toggle('active', state.fadeEnabled);
}

function toggleSpeedMenu() {
  const menu = $('#speed-menu');
  if (!menu) return;
  const willOpen = menu.hasAttribute('hidden');
  if (willOpen) {
    menu.removeAttribute('hidden');
    setTimeout(() => {
      document.addEventListener('click', onSpeedMenuOutsideClick);
    }, 0);
  } else {
    closeSpeedMenu();
  }
}

function closeSpeedMenu() {
  const menu = $('#speed-menu');
  if (menu) menu.setAttribute('hidden', '');
  document.removeEventListener('click', onSpeedMenuOutsideClick);
}

function onSpeedMenuOutsideClick(e) {
  const wrapper = e.target.closest('.speed-wrapper');
  if (!wrapper) closeSpeedMenu();
}

function syncPlaybackToView() {
  if (!playback.active || !playback.words.length) return;
  const newIndex = findFirstVisibleWordIndex();
  for (let i = 0; i < newIndex; i++) {
    playback.words[i].classList.add('revealed');
  }
  for (let i = newIndex; i < playback.words.length; i++) {
    playback.words[i].classList.remove('revealed');
  }
  playback.index = newIndex;
}

// --- Progress Bar Click ---

function onProgressClick(e) {
  if (!state.currentChapter) return;
  const track = e.currentTarget;
  const rect = track.getBoundingClientRect();
  const fraction = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));

  if (state.mode === 'scroll') {
    state.scrollFraction = fraction;
    applyScrollPosition(fraction);
    updateProgress();
    savePrefs();
  } else {
    const targetPage = Math.round(fraction * (state.totalPages - 1));
    goToPage(targetPage);
  }

  if (playback.active) {
    // Wait for scroll/page transition before resyncing cursor
    setTimeout(syncPlaybackToView, 350);
  }
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

// --- Citation Popovers ---

function setupCitationPopovers(container) {
  // Build reference map from numbered list
  const refMap = {};

  // Try <ol> whose items start with digits
  const ols = container.querySelectorAll('ol');
  let refOl = null;
  for (const ol of ols) {
    const firstLi = ol.querySelector('li');
    if (firstLi && /^\d/.test(firstLi.textContent.trim())) {
      refOl = ol;
      break;
    }
  }

  if (refOl) {
    const items = refOl.querySelectorAll('li');
    items.forEach((li, i) => {
      refMap[i + 1] = li.textContent.trim();
    });
  } else {
    // Fallback: <p> elements matching "N. text"
    const paras = container.querySelectorAll('p');
    paras.forEach(p => {
      const m = p.textContent.trim().match(/^(\d+)\.\s/);
      if (m) refMap[parseInt(m[1], 10)] = p.textContent.trim();
    });
  }

  if (!Object.keys(refMap).length) return;

  // Walk text nodes, skip .footnotes, headings, and the refOl
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      let p = node.parentElement;
      while (p && p !== container) {
        if (p.classList && (p.classList.contains('footnotes') || p.classList.contains('paper-meta'))) {
          return NodeFilter.FILTER_REJECT;
        }
        if (refOl && p === refOl) return NodeFilter.FILTER_REJECT;
        const tag = p.tagName;
        if (tag === 'H1' || tag === 'H2' || tag === 'H3' || tag === 'H4') {
          return NodeFilter.FILTER_REJECT;
        }
        p = p.parentElement;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });

  const textNodes = [];
  let node;
  while ((node = walker.nextNode())) textNodes.push(node);

  const citeRe = /(\d+)((?:,\s*\d+)*)/g;

  for (const textNode of textNodes) {
    const val = textNode.nodeValue;
    citeRe.lastIndex = 0;
    let match;
    const spans = [];
    let lastIdx = 0;

    while ((match = citeRe.exec(val)) !== null) {
      const full = match[0];
      const nums = full.split(',').map(s => parseInt(s.trim(), 10));
      if (!nums.every(n => refMap[n])) continue;

      spans.push({ start: match.index, end: match.index + full.length, nums });
    }

    if (!spans.length) continue;

    const frag = document.createDocumentFragment();
    for (const sp of spans) {
      if (lastIdx < sp.start) {
        frag.appendChild(document.createTextNode(val.slice(lastIdx, sp.start)));
      }
      const span = document.createElement('span');
      span.className = 'cite-ref';
      span.dataset.refs = sp.nums.join(',');
      span.textContent = val.slice(sp.start, sp.end);
      span.addEventListener('mouseover', (e) => {
        const refs = e.currentTarget.dataset.refs.split(',').map(Number);
        const html = refs.map(n => `<p>${refMap[n]}</p>`).join('');
        showFootnotePopover(html, e.clientX, e.clientY);
      });
      span.addEventListener('mouseout', dismissPopover);
      frag.appendChild(span);
      lastIdx = sp.end;
    }
    if (lastIdx < val.length) {
      frag.appendChild(document.createTextNode(val.slice(lastIdx)));
    }
    textNode.parentNode.replaceChild(frag, textNode);
  }
}

// --- Figure Popovers ---

function setupFigurePopovers(container, figuresData, chapterDir) {
  const figMap = {};
  if (figuresData && figuresData.length) {
    for (const fig of figuresData) {
      figMap[fig.figure_id] = fig;
    }
  }

  const figRe = /\b(Figure|Fig\.)\s+(S?\d+[A-Za-z]?)/g;

  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      let p = node.parentElement;
      while (p && p !== container) {
        if (p.classList && (p.classList.contains('footnotes') || p.classList.contains('paper-meta'))) {
          return NodeFilter.FILTER_REJECT;
        }
        p = p.parentElement;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });

  const textNodes = [];
  let node;
  while ((node = walker.nextNode())) textNodes.push(node);

  for (const textNode of textNodes) {
    const val = textNode.nodeValue;
    figRe.lastIndex = 0;
    let match;
    const spans = [];
    let lastIdx = 0;

    while ((match = figRe.exec(val)) !== null) {
      spans.push({ start: match.index, end: match.index + match[0].length, id: match[2], full: match[0] });
    }
    if (!spans.length) continue;

    const frag = document.createDocumentFragment();
    for (const sp of spans) {
      if (lastIdx < sp.start) {
        frag.appendChild(document.createTextNode(val.slice(lastIdx, sp.start)));
      }
      const span = document.createElement('span');
      span.className = 'fig-ref';
      span.dataset.figId = sp.id;
      span.textContent = sp.full;
      if (figMap[sp.id]) {
        span.addEventListener('click', () => showFigureModal(figMap[sp.id], chapterDir));
      }
      frag.appendChild(span);
      lastIdx = sp.end;
    }
    if (lastIdx < val.length) {
      frag.appendChild(document.createTextNode(val.slice(lastIdx)));
    }
    textNode.parentNode.replaceChild(frag, textNode);
  }
}

function showFigureModal(fig, chapterDir) {
  dismissFigureModal();
  const modal = document.createElement('div');
  modal.className = 'figure-modal';

  const content = document.createElement('div');
  content.className = 'figure-modal-content';

  const img = document.createElement('img');
  const imgBase = chapterDir ? BASE + chapterDir + '/' : BASE;
  img.src = imgBase + fig.image_path;
  img.alt = fig.caption || '';

  const caption = document.createElement('div');
  caption.className = 'figure-modal-caption';
  caption.textContent = fig.caption || '';

  content.appendChild(img);
  if (fig.caption) content.appendChild(caption);
  modal.appendChild(content);
  document.body.appendChild(modal);

  modal.addEventListener('click', (e) => {
    if (e.target === modal) dismissFigureModal();
  });
}

function dismissFigureModal() {
  document.querySelectorAll('.figure-modal').forEach(el => el.remove());
}

// --- Keyboard Navigation ---

function handleKeydown(e) {
  // Escape: close modal/popover, or return to library
  if (e.key === 'Escape') {
    if (document.querySelector('.figure-modal')) {
      dismissFigureModal();
    } else if (document.querySelector('.footnote-popover')) {
      dismissPopover();
    } else if (state.currentChapter) {
      showLibrary();
    }
    return;
  }

  // Only handle navigation in reader view
  if (!state.currentChapter) return;

  if (state.mode === 'scroll') {
    const inner = $('.reading-pane-inner');
    const step = inner.clientHeight * 0.9;
    if (e.key === 'ArrowDown' || e.key === ' ') {
      e.preventDefault();
      inner.scrollBy({ top: step, behavior: 'smooth' });
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      inner.scrollBy({ top: -step, behavior: 'smooth' });
    } else if (e.key === 'PageDown') {
      e.preventDefault();
      inner.scrollBy({ top: step, behavior: 'smooth' });
    } else if (e.key === 'PageUp') {
      e.preventDefault();
      inner.scrollBy({ top: -step, behavior: 'smooth' });
    } else if (e.key === 'Home') {
      e.preventDefault();
      inner.scrollTo({ top: 0, behavior: 'smooth' });
    } else if (e.key === 'End') {
      e.preventDefault();
      inner.scrollTo({ top: inner.scrollHeight, behavior: 'smooth' });
    }
    return;
  }

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
    if (!state.currentChapter) return;
    recalcPages();
    if (state.mode === 'scroll') {
      applyScrollPosition(state.scrollFraction);
    } else {
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
  updateModeButton();
  updateSpeedButton();
  updateFadeToggle();
  applyFadeDuration();
  $('.reader-view').classList.toggle('scroll-mode', state.mode === 'scroll');

  // Wire up buttons
  $('#btn-back').addEventListener('click', showLibrary);
  $('#btn-theme').addEventListener('click', cycleTheme);
  $('#btn-theme-library').addEventListener('click', cycleTheme);
  $('#btn-font-up').addEventListener('click', () => applyFontSize(state.fontSize + FONT_STEP));
  $('#btn-font-down').addEventListener('click', () => applyFontSize(state.fontSize - FONT_STEP));
  $('#btn-toc').addEventListener('click', toggleSidebar);
  $('#btn-mode').addEventListener('click', toggleMode);
  $('#btn-play').addEventListener('click', togglePlayback);
  $('#btn-restart-playback').addEventListener('click', restartPlayback);
  $('#btn-stop-playback').addEventListener('click', exitPlayback);
  $('#btn-speed').addEventListener('click', (e) => {
    e.stopPropagation();
    toggleSpeedMenu();
  });
  $$('#speed-menu .speed-option').forEach(opt => {
    opt.addEventListener('click', () => {
      setPlaybackSpeed(parseFloat(opt.dataset.speed));
      closeSpeedMenu();
    });
  });
  $('#btn-fade-toggle').addEventListener('click', (e) => {
    e.stopPropagation();
    toggleFade();
  });

  // Page turn click zones
  $('#zone-left').addEventListener('click', prevPage);
  $('#zone-right').addEventListener('click', nextPage);

  // Track scroll position in scroll mode
  $('.reading-pane-inner').addEventListener('scroll', () => {
    if (state.mode === 'scroll') onScrollModeScroll();
  });

  // Click progress bar to jump
  $('.progress-track').addEventListener('click', onProgressClick);

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
