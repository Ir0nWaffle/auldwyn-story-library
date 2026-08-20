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

let currentBook = null;   // epub.js Book instance, so Back can .destroy() it
let currentRendition = null;

function showStatus(message, isError) {
  statusEl.textContent = message;
  statusEl.hidden = false;
  statusEl.classList.toggle("error", Boolean(isError));
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
  libraryView.hidden = true;
  readerView.hidden = false;
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
  currentRendition.display();
}

function closeReader() {
  if (currentRendition) currentRendition.destroy();
  if (currentBook) currentBook.destroy();
  currentRendition = null;
  currentBook = null;
  readerView.hidden = true;
  libraryView.hidden = false;
}

backBtn.addEventListener("click", closeReader);
prevBtn.addEventListener("click", () => currentRendition && currentRendition.prev());
nextBtn.addEventListener("click", () => currentRendition && currentRendition.next());
document.addEventListener("keydown", (e) => {
  if (readerView.hidden || !currentRendition) return;
  if (e.key === "ArrowLeft") currentRendition.prev();
  if (e.key === "ArrowRight") currentRendition.next();
  if (e.key === "Escape") closeReader();
});

loadLibrary();
