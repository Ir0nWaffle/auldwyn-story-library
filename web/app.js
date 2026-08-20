/*
 * Auldwyn Library embed logic: fetch the catalog, render the grid, and
 * drive an epub.js reader for the "Read" button.
 *
 * API base path: this page is mounted at /embed (see library_api/app.py's
 * `app.mount("/embed", ...)`), which is served both directly off the
 * container root (local/dev -- e.g. http://localhost:8083/embed/) *and*
 * publicly behind Tailscale Funnel's path mount (e.g.
 * https://<host>:8443/library/embed/, with "/library" stripped before it
 * ever reaches this container -- see that README's "Public access"
 * section). A hardcoded "/api/stories" would break under the public
 * prefix; a *relative* "../api/stories" resolves correctly in the
 * browser either way, since relative-URL resolution just drops the
 * current page's last path segment and applies the reference -- entirely
 * a client-side string operation, unaware of (and unaffected by) how the
 * server-side prefix stripping works. One level up from /embed/ lands on
 * the same root /api, /covers, /books routes app.py already serves.
 *
 * The catalog JSON's own cover_url/epub_url fields don't need this same
 * trick -- library_api already bakes the correct public-facing prefix
 * into those (via PUBLIC_URL_PREFIX server-side), so they're used as-is.
 */
const API_STORIES_URL = "../api/stories";

const libraryView = document.getElementById("library-view");
const readerView = document.getElementById("reader-view");
const statusEl = document.getElementById("status");
const gridEl = document.getElementById("grid");
const backBtn = document.getElementById("back-btn");
const readerTitle = document.getElementById("reader-title");
const readerDownload = document.getElementById("reader-download");
const viewerEl = document.getElementById("viewer");
const prevBtn = document.getElementById("prev-btn");
const nextBtn = document.getElementById("next-btn");
const fullscreenBtn = document.getElementById("fullscreen-btn");
const themeBtn = document.getElementById("theme-btn");
const tapPrev = document.getElementById("tap-prev");
const tapToggle = document.getElementById("tap-toggle");
const tapNext = document.getElementById("tap-next");

let currentBook = null;   // epub.js Book instance, so Back can .destroy() it
let currentRendition = null;

// Two epub.js "themes" (see https://github.com/futurepress/epub.js --
// Rendition#themes.register/select) -- each is a plain selector->CSS
// object epub.js injects as a <style> into every chapter's own iframe,
// which is the only way to recolor content that lives in a different
// document than this page. !important on every property because the
// generated stories (common/epub_builder.py) don't set body color/
// background at all today, but there's no guarantee a future story
// (or one from elsewhere) won't -- without it, this theme would lose to
// even a low-specificity same-selector rule already in the book. Colors
// come from auldwyn.net's own palette (see style.css's top comment for
// where these were pulled from), not invented separately: "dark" uses
// its exact body background/text colors, so dark mode ends up matching
// the site's own default look outright; "light" uses its lightest
// greige tone as a comfortable reading surface with near-black text.
const READER_THEMES = {
  light: {
    body: { color: "#171717 !important", background: "#e7e2d8 !important" },
  },
  dark: {
    body: { color: "#d8d4cc !important", background: "#171717 !important" },
    a: { color: "#d0ad70 !important" },
  },
};
const READER_THEME_STORAGE_KEY = "auldwynReaderTheme";

function loadReaderTheme() {
  try {
    return localStorage.getItem(READER_THEME_STORAGE_KEY) === "dark" ? "dark" : "light";
  } catch {
    // Storage can throw rather than just fail (e.g. a sandboxed iframe
    // embed without allow-same-origin, or a browser privacy mode) --
    // reading preference just isn't remembered across visits in that
    // case, not worth failing the reader over.
    return "light";
  }
}

function saveReaderTheme(theme) {
  try {
    localStorage.setItem(READER_THEME_STORAGE_KEY, theme);
  } catch {
    // Same as above -- best effort only.
  }
}

let readerTheme = loadReaderTheme();

let controlsHideTimer = null;
const CONTROLS_IDLE_MS = 2500; // "a couple of seconds"

// Reveals the toolbar and, only while actually fullscreen, arms a timer
// to hide it again after CONTROLS_IDLE_MS of no further activity -- in
// the normal windowed/embedded view the toolbar has nowhere better to
// go and no touch-only way to bring it back, so it just stays visible
// there (this still runs safely in that case, it just never re-hides).
function showControls() {
  readerView.classList.add("show-controls");
  clearTimeout(controlsHideTimer);
  if (isFullscreen()) {
    controlsHideTimer = setTimeout(() => {
      readerView.classList.remove("show-controls");
    }, CONTROLS_IDLE_MS);
  }
}

let _statusHideTimer = null;

function showStatus(message, isError, autoHideMs) {
  clearTimeout(_statusHideTimer);
  statusEl.textContent = message;
  statusEl.hidden = false;
  statusEl.classList.toggle("error", Boolean(isError));
  // autoHideMs is for transient notices (e.g. the fullscreen-permission
  // warning below) -- omit it for a standing state like "no stories yet"
  // or "could not reach the library", which should stay up until the
  // underlying thing they describe changes.
  if (autoHideMs) _statusHideTimer = setTimeout(() => { statusEl.hidden = true; }, autoHideMs);
}

function cardFor(story) {
  const card = document.createElement("div");
  card.className = "card";

  const img = document.createElement("img");
  img.className = "cover";
  img.loading = "lazy";
  img.src = story.cover_url;
  img.alt = `Cover of ${story.title}`;
  card.appendChild(img);

  const h3 = document.createElement("h3");
  h3.textContent = story.title;
  card.appendChild(h3);

  const author = document.createElement("p");
  author.className = "author";
  author.textContent = `by ${story.author}`;
  card.appendChild(author);

  const summary = document.createElement("p");
  summary.className = "summary";
  summary.textContent = story.summary || "";
  card.appendChild(summary);

  const actions = document.createElement("div");
  actions.className = "card-actions";

  const readBtn = document.createElement("button");
  readBtn.className = "btn btn-gold";
  readBtn.textContent = "Read";
  readBtn.addEventListener("click", () => openReader(story));
  actions.appendChild(readBtn);

  const downloadLink = document.createElement("a");
  downloadLink.className = "btn";
  downloadLink.textContent = "Download EPUB";
  downloadLink.href = story.epub_url;
  downloadLink.download = `${story.title}.epub`;
  actions.appendChild(downloadLink);

  card.appendChild(actions);
  return card;
}

async function loadLibrary() {
  showStatus("Loading stories…", false);
  try {
    const resp = await fetch(API_STORIES_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const stories = await resp.json();
    statusEl.hidden = true;
    gridEl.innerHTML = "";
    for (const story of stories) gridEl.appendChild(cardFor(story));
    if (stories.length === 0) showStatus("No stories in the catalog yet.", false);
  } catch (err) {
    showStatus(`Could not reach the library: ${err.message}`, true);
  }
}

function openReader(story) {
  // reading-mode hides .site-header (see style.css) so #reader-view --
  // already flex: 1 1 auto in the body's own flex column -- takes over
  // the entire frame instead of sitting in whatever space is left under
  // a header that's still taking up room. This is the actual fix for
  // "the reader is stuck at the bottom of the screen": before, the
  // header never went anywhere, so the reader was just one more block
  // in the flow below it rather than the whole page.
  document.body.classList.add("reading-mode");
  libraryView.hidden = true;
  readerView.hidden = false;
  showControls(); // visible the moment a book opens; harmless no-op pre-fullscreen
  readerTitle.textContent = story.title;
  readerDownload.href = story.epub_url;
  readerDownload.download = `${story.title}.epub`;

  viewerEl.innerHTML = "";
  currentBook = ePub(story.epub_url);
  currentRendition = currentBook.renderTo(viewerEl, {
    width: "100%",
    height: "100%",
    flow: "paginated",
    spread: "auto",
  });
  currentRendition.themes.register("light", READER_THEMES.light);
  currentRendition.themes.register("dark", READER_THEMES.dark);
  applyReaderTheme(); // selects whichever theme was last chosen, and syncs #viewer + the button label to match
  currentRendition.display();
}

// Selects the theme on the rendition and syncs the viewer background/
// button label -- nothing more. Deliberately does NOT force a redisplay
// (see toggleReaderTheme() below for why that's sometimes needed) --
// this alone is exactly right for openReader()'s use of it below, where
// the rendition's own first display() call, made right after this
// returns, already renders correctly under whichever theme was just
// selected. Forcing a redisplay here too doesn't fix anything further in
// that case -- it races that first display() call instead, and was
// actually what left newly-opened books showing a blank page.
function selectReaderTheme(theme) {
  viewerEl.classList.toggle("theme-dark", theme === "dark");
  themeBtn.textContent = theme === "dark" ? "☀️ Light Mode" : "🌙 Dark Mode";
  if (currentRendition) currentRendition.themes.select(theme);
}

function applyReaderTheme() {
  selectReaderTheme(readerTheme);
}

function toggleReaderTheme() {
  readerTheme = readerTheme === "dark" ? "light" : "dark";
  saveReaderTheme(readerTheme);
  selectReaderTheme(readerTheme);
  if (!currentRendition) return;
  // Only needed here, toggling on a book that's ALREADY displayed:
  // themes.select() is meant to live-restyle whatever page is already on
  // screen, but that doesn't reliably happen in practice (a known rough
  // edge in epub.js's Themes API, not something wrong with the theme
  // rules themselves -- newly-turned-to pages pick up the change fine,
  // just not the one already displayed when select() was called). The
  // documented workaround is to force that exact page to redraw: ask
  // epub.js for the CFI of exactly where it's currently showing, then
  // display() that same location again.
  const location = currentRendition.currentLocation();
  const cfi = location && location.start && location.start.cfi;
  if (cfi) currentRendition.display(cfi);
}

function isFullscreen() {
  return Boolean(document.fullscreenElement || document.webkitFullscreenElement);
}

function closeReader() {
  if (isFullscreen()) {
    (document.exitFullscreen || document.webkitExitFullscreen)?.call(document);
  }
  clearTimeout(controlsHideTimer);
  if (currentRendition) currentRendition.destroy();
  if (currentBook) currentBook.destroy();
  currentRendition = null;
  currentBook = null;
  document.body.classList.remove("reading-mode");
  readerView.hidden = true;
  libraryView.hidden = false;
}

function updateFullscreenLabel() {
  fullscreenBtn.textContent = isFullscreen() ? "⛶ Exit Full Screen" : "⛶ Full Screen";
}

function handleFullscreenChange() {
  updateFullscreenLabel();
  // epub.js measures #viewer's box once at renderTo() time and doesn't
  // watch for it changing size on its own -- entering/leaving fullscreen
  // resizes that box without ever firing a window "resize" event, so
  // without this the book's own rendered page stays locked at its
  // pre-fullscreen size while just the surrounding chrome grows, which
  // looks like "fullscreen didn't really fill the screen" even though
  // the element itself did. rendition.resize() with no arguments makes
  // epub.js re-measure its container instead of trusting stale numbers.
  // Deferred one frame: fullscreenchange can fire a tick before the
  // element's new geometry is actually settled on some mobile browsers,
  // so measuring synchronously here would still read the old size.
  requestAnimationFrame(() => currentRendition && currentRendition.resize());

  if (isFullscreen()) {
    showControls(); // visible now, arms the auto-hide timer
  } else {
    // Back in the normal windowed view -- no auto-hide there, so make
    // sure the toolbar can't be left mid-fade-out from a moment ago.
    clearTimeout(controlsHideTimer);
    readerView.classList.add("show-controls");
  }
}

function toggleFullscreen() {
  if (isFullscreen()) {
    (document.exitFullscreen || document.webkitExitFullscreen)?.call(document);
    return;
  }
  const request = readerView.requestFullscreen || readerView.webkitRequestFullscreen;
  if (!request) return; // Fullscreen API not available in this browser at all
  Promise.resolve(request.call(readerView)).catch(() => {
    // Most likely cause when this page is embedded elsewhere: the
    // parent site's own <iframe> tag is missing allow="fullscreen" --
    // see index.html's top comment. The Fullscreen API silently refuses
    // rather than throwing somewhere useful, so there's nothing more
    // specific to tell the user here.
    showStatus(
      "This page's iframe embed needs allow=\"fullscreen\" for Full Screen to work.",
      true,
      4000
    );
  });
}

backBtn.addEventListener("click", closeReader);
prevBtn.addEventListener("click", () => { currentRendition && currentRendition.prev(); showControls(); });
nextBtn.addEventListener("click", () => { currentRendition && currentRendition.next(); showControls(); });
themeBtn.addEventListener("click", toggleReaderTheme);
fullscreenBtn.addEventListener("click", toggleFullscreen);
document.addEventListener("fullscreenchange", handleFullscreenChange);
document.addEventListener("webkitfullscreenchange", handleFullscreenChange);

// Page-turn/reveal-controls tap zones -- see index.html's comment on why
// these exist as overlay divs rather than listening on the book content
// itself. All three call showControls(): left/right so turning a page
// also counts as activity (otherwise the toolbar could fade out mid-
// read the instant after it was last shown), middle as the touch
// equivalent of the mousemove listener below.
tapPrev.addEventListener("click", () => { currentRendition && currentRendition.prev(); showControls(); });
tapNext.addEventListener("click", () => { currentRendition && currentRendition.next(); showControls(); });
tapToggle.addEventListener("click", showControls);

// Desktop: moving the mouse anywhere over the reader (including directly
// over the toolbar/buttons, via bubbling) counts as activity.
// pointerdown covers touch taps that land on the toolbar itself or on
// #reader-view's own background, on top of the tap-zone-specific
// handlers above.
readerView.addEventListener("mousemove", showControls);
readerView.addEventListener("pointerdown", showControls);

document.addEventListener("keydown", (e) => {
  if (readerView.hidden || !currentRendition) return;
  if (e.key === "ArrowLeft") { currentRendition.prev(); showControls(); }
  if (e.key === "ArrowRight") { currentRendition.next(); showControls(); }
  // Escape while fullscreen is left to the browser's own native
  // fullscreen-exit handling (which fires fullscreenchange, above) --
  // only leave the reader entirely on a *second*, non-fullscreen
  // Escape, so one Escape doesn't both drop fullscreen and abandon the
  // book in a single keystroke.
  if (e.key === "Escape" && !isFullscreen()) closeReader();
});

loadLibrary();
