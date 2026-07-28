/* Pinterest Picture Books — front-end logic. */

const App = {
  tab: 1,
  loggedIn: false,
  username: null,
  boards: [],        // boards available to select in Tab 2 (from login + URLs)
  downloaded: [],    // boards that already have pin data on disk
  bookCss: "",
};

const TABS = [
  { n: 1, title: "Login",  color: "bg-amber-500" },
  { n: 2, title: "Boards", color: "bg-sky-500" },
  { n: 3, title: "Books",  color: "bg-emerald-500" },
];

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

/* ----------------------------------------------------------------------- */
/* Toasts                                                                    */
/* ----------------------------------------------------------------------- */
function toast(message, type = "info", opts = {}) {
  const colors = {
    info: "bg-slate-800",
    success: "bg-emerald-600",
    error: "bg-red-600",
    progress: "bg-slate-800",
  };
  const el = document.createElement("div");
  el.className = `${colors[type]} text-white rounded-xl shadow-lg px-4 py-3 text-sm animate-[fadein_.2s]`;
  el.innerHTML = `<div class="toast-body">${message}</div>`;
  if (opts.progress) {
    el.innerHTML += `
      <div class="mt-2 h-1.5 bg-white/25 rounded-full overflow-hidden">
        <div class="toast-bar h-full bg-white rounded-full transition-all" style="width:0%"></div>
      </div>`;
  }
  $("#toasts").appendChild(el);
  if (!opts.sticky) {
    setTimeout(() => el.remove(), opts.duration || 3500);
  }
  return el;
}

/* ----------------------------------------------------------------------- */
/* Tabs & navigation                                                         */
/* ----------------------------------------------------------------------- */
function renderTabs() {
  $("#tabs").innerHTML = TABS.map((t) => {
    const active = t.n === App.tab;
    return `
      <button data-tab="${t.n}"
        class="flex items-center gap-2 px-4 py-2 rounded-t-lg border-b-2 ${
          active ? "border-brand text-slate-900 font-semibold" : "border-transparent text-slate-400"
        }">
        <span class="${t.color} text-white w-6 h-6 rounded-full grid place-items-center text-xs font-bold">${t.n}</span>
        ${t.title}
      </button>`;
  }).join("");
  $$("#tabs [data-tab]").forEach((b) =>
    b.addEventListener("click", () => goTab(Number(b.dataset.tab)))
  );
}

function goTab(n) {
  App.tab = n;
  $$("[data-panel]").forEach((p) => p.classList.toggle("hidden", Number(p.dataset.panel) !== n));
  renderTabs();
  updateNav();
  if (n === 3) refreshBookTab();
}

function updateNav() {
  const back = $("#back-btn"), skip = $("#skip-btn"), next = $("#next-btn");
  back.disabled = App.tab === 1;                 // cannot go back from tab 1
  skip.classList.toggle("hidden", App.tab !== 1); // Skip only makes sense at login
  next.classList.toggle("hidden", App.tab === 3); // cannot go forward from last tab
  if (App.tab === 1) {
    next.disabled = !App.loggedIn;               // Next enabled only once logged in
  } else {
    next.disabled = false;
  }
}

/* ----------------------------------------------------------------------- */
/* Tab 1 — Login                                                             */
/* ----------------------------------------------------------------------- */
async function doLogin() {
  const email = $("#login-email").value.trim();
  const password = $("#login-password").value;
  const username = $("#login-username").value.trim();
  if (!email || !password) {
    toast("Enter your email and password.", "error");
    return;
  }
  const btn = $("#login-btn");
  btn.disabled = true;
  btn.textContent = "Logging in…";
  const waiting = toast(
    "A Chrome window is opening. If it isn't filled in automatically, sign in " +
    "there manually — we'll capture your session when you're done.",
    "info", { sticky: true });
  const res = await eel.do_login(email, password, username)();
  waiting.remove();
  btn.disabled = false;
  btn.textContent = "Log in";
  if (res.ok) {
    App.loggedIn = true;
    App.username = res.username || null;
    const who = res.username ? `as ${res.username}` : "(username not detected)";
    $("#login-status").innerHTML =
      `<span class="text-emerald-600 font-medium">✓ Logged in ${who}</span>`;
    toast(`Logged in ${who}`, "success");
    if (res.username) {
      await loadUserBoards();
    } else {
      toast("Signed in. Add the Username above to list your own boards, " +
            "or add boards by URL on the next tab.", "info", { duration: 7000 });
    }
    updateNav();
  } else {
    toast(res.error || "Login failed.", "error", { duration: 6000 });
  }
}

/* ----------------------------------------------------------------------- */
/* Tab 2 — Boards                                                            */
/* ----------------------------------------------------------------------- */
async function loadUserBoards() {
  const res = await eel.get_user_boards()();
  if (res.ok) {
    mergeBoards(res.boards, true);
    renderBoardList();
  } else if (App.loggedIn) {
    toast(res.error, "error");
  }
}

function mergeBoards(newBoards, selectByDefault) {
  const byId = new Map(App.boards.map((b) => [b.id, b]));
  for (const b of newBoards) {
    if (!byId.has(b.id)) {
      b.selected = selectByDefault; // all selected by default
      App.boards.push(b);
      byId.set(b.id, b);
    }
  }
}

function renderBoardList() {
  const list = $("#board-list");
  $("#board-count").textContent = App.boards.length;
  if (App.boards.length === 0) {
    list.innerHTML = `<li class="p-4 text-sm text-slate-400 text-center">
      No boards yet — log in to load yours, or add one by URL above.</li>`;
    return;
  }
  list.innerHTML = App.boards.map((b, i) => `
    <li class="flex items-center gap-3 px-4 py-2.5">
      <input type="checkbox" data-i="${i}" class="board-cb accent-brand w-4 h-4" ${b.selected ? "checked" : ""}>
      <div class="flex-1 min-w-0">
        <div class="font-medium truncate">${b.name}</div>
        <div class="text-xs text-slate-400 truncate">${b.pin_count || 0} pins · ${b.privacy || "public"}</div>
      </div>
    </li>`).join("");
  $$(".board-cb").forEach((cb) =>
    cb.addEventListener("change", () => { App.boards[cb.dataset.i].selected = cb.checked; })
  );
}

async function addBoardByUrl() {
  const input = $("#board-url");
  const url = input.value.trim();
  if (!url) return;
  const btn = $("#add-url-btn");
  btn.disabled = true;
  const res = await eel.add_board_url(url)();
  btn.disabled = false;
  if (res.ok) {
    mergeBoards([res.board], true);
    renderBoardList();
    input.value = "";
    toast(`Added “${res.board.name}”`, "success");
  } else {
    toast(res.error, "error", { duration: 6000 });
  }
}

async function smartDownload() {
  const selected = App.boards.filter((b) => b.selected);
  if (selected.length === 0) {
    toast("Select at least one board.", "error");
    return;
  }
  const bar = toast("Starting Smart Download…", "progress", { sticky: true, progress: true });
  App._dlToast = bar;
  await eel.start_download(selected)();
}

// Called from Python during download.
function download_progress(p) {
  const bar = App._dlToast;
  if (!bar) return;
  const body = bar.querySelector(".toast-body");
  const fill = bar.querySelector(".toast-bar");
  let pct = ((p.board_index - 1) / p.board_total) * 100;
  let msg = `Board ${p.board_index}/${p.board_total}: ${p.board}`;
  if (p.phase === "fetching") {
    msg += `<br><span class="opacity-80">Fetching new pins… (${p.new})</span>`;
  } else if (p.phase === "images") {
    msg += `<br><span class="opacity-80">Saving images ${p.done}/${p.new}</span>`;
    pct += (p.done / Math.max(1, p.new)) * (100 / p.board_total);
  } else if (p.phase === "board_done") {
    msg += `<br><span class="opacity-80">+${p.new} new · ${p.total} total</span>`;
    pct = (p.board_index / p.board_total) * 100;
  }
  body.innerHTML = msg;
  fill.style.width = `${Math.min(100, pct)}%`;
}

// Called from Python when the whole download finishes.
function download_done(r) {
  const bar = App._dlToast;
  App._dlToast = null;
  if (bar) bar.remove();
  if (r.ok) {
    App.downloaded = r.downloaded || [];
    toast(`Done — ${r.new} new pin(s) downloaded.`, "success");
  } else {
    toast(r.error || "Download failed.", "error", { duration: 6000 });
  }
}

/* ----------------------------------------------------------------------- */
/* Tab 3 — Books                                                             */
/* ----------------------------------------------------------------------- */
const PAGE_KEYWORD = { a4: "A4", letter: "Letter", a5: "A5" };

function collectOptions() {
  const selectedFolders = $$("#board-picker input:checked").map((cb) => cb.dataset.folder);
  return {
    source_mode: $("#opt-source").value,
    selected_folders: selectedFolders,
    page_size: $("#opt-page-size").value,
    orientation: $("#opt-orientation").value,
    columns: Number($("#opt-columns").value),
    order: $("#opt-order").value,
    gutter_mm: Number($("#opt-gutter").value),
    margin_mm: Number($("#opt-margin").value),
    max_images: Number($("#opt-max").value),
    max_per_page: Number($("#opt-per-page").value),
    crop: $("#opt-crop").checked,
    show_titles: $("#opt-titles").checked,
    show_filenames: $("#opt-files").checked,
    show_dates: $("#opt-dates").checked,
    show_board: $("#opt-board").checked,
    page_numbers: $("#opt-pagenums").checked,
    cover: $("#opt-cover").checked,
    book_title: $("#opt-title").value,
    book_subtitle: $("#opt-subtitle").value,
  };
}

async function refreshBookTab() {
  const res = await eel.list_boards_with_data()();
  if (res.ok) App.downloaded = res.downloaded || [];
  renderBoardPicker();
}

function renderBoardPicker() {
  const picker = $("#board-picker");
  if (App.downloaded.length === 0) {
    picker.innerHTML = `<div class="text-xs text-slate-400">No downloaded boards yet.</div>`;
    return;
  }
  picker.innerHTML = App.downloaded.map((b) => `
    <label class="flex items-center gap-2 text-sm py-0.5">
      <input type="checkbox" data-folder="${b.folder}" checked class="accent-brand">
      <span class="truncate">${b.name} <span class="text-slate-400">(${b.count})</span></span>
    </label>`).join("");
}

async function buildBook() {
  await ensureBookCss(); // guarantees tile positioning rules are present
  const options = collectOptions();
  const btn = $("#build-btn");
  btn.disabled = true;
  btn.textContent = "Building…";
  const res = await eel.build_book(options)();
  btn.disabled = false;
  btn.textContent = "↻ Update preview";
  if (!res.ok) {
    toast(res.error, "error");
    return;
  }
  // Dynamic @page rule so print output matches the chosen size.
  $("#print-page").textContent =
    `@page { size: ${PAGE_KEYWORD[options.page_size]} ${options.orientation}; margin: 0; }`;

  const book = $("#book");
  book.innerHTML = res.html;
  $("#preview-empty").classList.add("hidden");
  $("#preview-meta").textContent =
    `${res.pin_count} images · ${res.page_count} page(s)`;
  scalePreview(res.page_w);
}

// Fit A4-width pages inside the preview column using CSS zoom (Chromium).
function scalePreview(pageW) {
  const container = $("#book").parentElement.parentElement; // scroll area
  const avail = container.clientWidth - 48;
  const scale = Math.min(1, avail / pageW);
  $("#book").style.zoom = scale;
}

async function exportPdf() {
  const btn = $("#pdf-btn");
  btn.disabled = true;
  btn.textContent = "Rendering…";
  const res = await eel.export_pdf(collectOptions())();
  btn.disabled = false;
  btn.textContent = "⬇ Save PDF";
  if (res.ok) {
    toast(`Saved PDF → ${res.path}`, "success", { duration: 6000 });
  } else {
    toast(res.error || "PDF export failed. Try Print → Save as PDF instead.",
          "error", { duration: 7000 });
  }
}

/* ----------------------------------------------------------------------- */
/* Wiring                                                                    */
/* ----------------------------------------------------------------------- */
function wire() {
  // Bottom nav
  $("#back-btn").addEventListener("click", () => { if (App.tab > 1) goTab(App.tab - 1); });
  $("#next-btn").addEventListener("click", () => { if (App.tab < 3) goTab(App.tab + 1); });
  $("#skip-btn").addEventListener("click", () => goTab(2)); // skip login

  // Tab 1
  $("#login-btn").addEventListener("click", doLogin);

  // Tab 2
  $("#add-url-btn").addEventListener("click", addBoardByUrl);
  $("#board-url").addEventListener("keydown", (e) => { if (e.key === "Enter") addBoardByUrl(); });
  $("#refresh-boards").addEventListener("click", loadUserBoards);
  $("#select-all").addEventListener("click", () => { App.boards.forEach((b) => b.selected = true); renderBoardList(); });
  $("#select-none").addEventListener("click", () => { App.boards.forEach((b) => b.selected = false); renderBoardList(); });
  $("#smart-download-btn").addEventListener("click", smartDownload);

  // Tab 3
  $("#opt-source").addEventListener("change", (e) =>
    $("#board-picker").classList.toggle("hidden", e.target.value !== "select"));
  $("#opt-cover").addEventListener("change", (e) =>
    $("#cover-fields").classList.toggle("hidden", !e.target.checked));
  $("#opt-columns").addEventListener("input", (e) => { $("#cols-val").textContent = e.target.value; });
  $("#build-btn").addEventListener("click", buildBook);
  $("#print-btn").addEventListener("click", () => {
    if (!$("#book").innerHTML.trim()) { toast("Build the preview first.", "error"); return; }
    window.print();
  });
  $("#pdf-btn").addEventListener("click", exportPdf);

  // Expose callbacks for Python-initiated progress updates.
  eel.expose(download_progress, "download_progress");
  eel.expose(download_done, "download_done");
}

// Load the book stylesheet (absolute-positioning rules for pages/tiles) from
// Python and inject it. Without this, tiles fall back to block flow — one
// column that overflows the pages — so the preview MUST have it before render.
async function ensureBookCss() {
  if (App.bookCss) return true;
  const res = await eel.get_book_css()();
  if (res && res.ok) {
    App.bookCss = res.css;
    document.getElementById("book-css").textContent = res.css;
    return true;
  }
  return false;
}

async function boot() {
  renderTabs();
  wire();
  updateNav();
  await ensureBookCss();
  const res = await eel.init_app()();
  if (res && res.ok) {
    App.downloaded = res.downloaded || [];
    if (res.logged_in) {
      App.loggedIn = true;
      App.username = res.username || null;
      const who = res.username ? `as ${res.username}` : "(username not detected)";
      $("#login-status").innerHTML =
        `<span class="text-emerald-600 font-medium">✓ Session restored ${who}</span>`;
      if (res.username) await loadUserBoards();
    }
  }
  updateNav();
}

window.addEventListener("DOMContentLoaded", boot);
