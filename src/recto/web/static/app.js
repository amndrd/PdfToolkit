/* Recto — offline UI.
 *
 * Vanilla JavaScript: no build step, no bundler, no dependencies. The whole
 * interface is generated from GET /api/tools, so adding a tool to the registry
 * in web/tools.py makes it appear here without touching this file.
 *
 * The one piece of duplicated logic is the page-range dialect below, mirrored
 * from recto/ranges.py so that clicking a page can fill the field and typing
 * in the field can highlight pages. The server re-parses everything on submit
 * and remains the authority; this copy is a convenience only.
 */

"use strict";

const state = {
  tools: [],
  previews: true,
  tool: null,        // active tool id
  group: null,       // active category
  files: [],         // {id, name, size, pages, encrypted, error}
  selected: [],      // file ids, in the order chosen — merge order
  active: null,      // file id whose pages are on screen
  sequence: [],      // 1-based page numbers picked, in click order
};

const el = (id) => document.getElementById(id);
const ui = {
  navbar: el("navbar"),
  doc: el("doc"),
  landing: el("landing"),
  workspace: el("workspace"),
  restart: el("restart"),
  dropcard: el("dropcard"),
  dropveil: el("dropveil"),
  picker: el("picker"),
  addmore: el("addmore"),
  navtabs: el("navtabs"),
  panel: el("panel"),
  panelTitle: el("panel-title"),
  panelDesc: el("panel-desc"),
  form: el("optionsform"),
  run: el("run"),
  requirement: el("requirement"),
  status: el("status"),
  results: el("results"),
  filerail: el("filerail"),
  pagehint: el("pagehint"),
  pagegrid: el("pagegrid"),
};

/* ═══════════════════════════════════════════════════════ page-range dialect */

function formatRange(numbers) {
  const sorted = [...new Set(numbers)].sort((a, b) => a - b);
  if (!sorted.length) return "";
  const chunks = [];
  let start = sorted[0];
  let previous = sorted[0];
  for (const value of sorted.slice(1)) {
    if (value === previous + 1) { previous = value; continue; }
    chunks.push(chunkOf(start, previous));
    start = previous = value;
  }
  chunks.push(chunkOf(start, previous));
  return chunks.join(",");
}

function chunkOf(start, end) {
  if (start === end) return `${start}`;
  if (end === start + 1) return `${start},${end}`;
  return `${start}-${end}`;
}

function parseRange(text, total) {
  const found = new Set();
  if (!text || !text.trim()) return found;

  const resolve = (token) =>
    token === "first" ? 1 : token === "last" ? total : parseInt(token, 10);
  const span = (from, to) => {
    const step = to >= from ? 1 : -1;
    for (let i = from; step > 0 ? i <= to : i >= to; i += step) {
      if (i >= 1 && i <= total) found.add(i);
    }
  };

  for (const raw of text.split(",")) {
    const part = raw.replace(/\s+/g, "").toLowerCase();
    if (!part) continue;

    if (part === "all" || part === "*") { span(1, total); continue; }
    if (part === "odd") { for (let i = 1; i <= total; i += 2) found.add(i); continue; }
    if (part === "even") { for (let i = 2; i <= total; i += 2) found.add(i); continue; }

    const N = "(\\d+|first|last)";
    let match;
    if ((match = part.match(new RegExp(`^${N}-${N}$`)))) {
      span(resolve(match[1]), resolve(match[2]));
    } else if ((match = part.match(new RegExp(`^${N}-$`)))) {
      span(resolve(match[1]), total);
    } else if ((match = part.match(new RegExp(`^-${N}$`)))) {
      span(1, resolve(match[1]));
    } else if ((match = part.match(new RegExp(`^${N}$`)))) {
      span(resolve(match[1]), resolve(match[1]));
    }
  }
  return found;
}

/* ════════════════════════════════════════════════════════════════ helpers */

function humanSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  let value = bytes;
  for (const unit of ["KB", "MB", "GB"]) {
    value /= 1024;
    if (value < 1024) return `${value.toFixed(1)} ${unit}`;
  }
  return `${(value / 1024).toFixed(1)} TB`;
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function icon(path, size = 12) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("aria-hidden", "true");
  const shape = document.createElementNS("http://www.w3.org/2000/svg", "path");
  shape.setAttribute("d", path);
  shape.setAttribute("fill", "none");
  shape.setAttribute("stroke", "currentColor");
  shape.setAttribute("stroke-width", "2.2");
  shape.setAttribute("stroke-linecap", "round");
  shape.setAttribute("stroke-linejoin", "round");
  svg.appendChild(shape);
  return svg;
}

const CHECK = "M3 8.5 6.5 12 13 4.5";

async function api(path, options) {
  const response = await fetch(path, options);
  const isJson = (response.headers.get("content-type") || "").includes("json");
  const body = isJson ? await response.json() : null;
  if (!response.ok) {
    throw new Error((body && body.detail) || `Request failed (${response.status})`);
  }
  return body;
}

function setStatus(message, kind) {
  ui.status.textContent = message || "";
  ui.status.className = `status${kind ? ` ${kind}` : ""}`;
}

const MOTION_OK = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const currentTool = () => state.tools.find((t) => t.id === state.tool) || null;
const activeFile = () => state.files.find((f) => f.id === state.active) || null;

/** The field a page click should fill, if the active tool has one. */
function pageField() {
  const tool = currentTool();
  if (!tool) return null;
  const field = tool.fields.find((f) => f.kind === "pages");
  if (!field) return null;
  const wrapper = ui.form.querySelector(`[data-name="${field.name}"]`);
  if (wrapper && wrapper.classList.contains("hidden")) return null;
  return field;
}

/** `order` reads as a sequence; every other page field reads as a set. */
const fieldIsOrdered = (field) => field && field.name === "order";

/* ═══════════════════════════════════════════════════════════════════ files */

async function addFiles(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) return;

  const form = new FormData();
  files.forEach((file) => form.append("files", file, file.name));

  setStatus(`Reading ${files.length} file${files.length === 1 ? "" : "s"}…`, "working");
  try {
    const data = await api("/api/files", { method: "POST", body: form });
    state.files.push(...data.files);
    data.files.forEach((file) => {
      if (!state.selected.includes(file.id)) state.selected.push(file.id);
    });
    if (!state.active && data.files.length) state.active = data.files[0].id;

    setStatus("");
    if (ui.landing.classList.contains("hidden")) {
      renderFiles();
      renderPages();
      updateRun();
    } else {
      await growCardIntoWorkspace();
    }
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function removeFile(id) {
  state.files = state.files.filter((f) => f.id !== id);
  state.selected = state.selected.filter((s) => s !== id);
  if (state.active === id) state.active = state.files.length ? state.files[0].id : null;
  state.sequence = [];

  if (!state.files.length) {
    leaveWorkspace();
  } else {
    renderFiles();
    renderPages();
    updateRun();
  }
  try {
    await api(`/api/files/${id}`, { method: "DELETE" });
  } catch { /* already gone from the UI; nothing useful to add */ }
}

function chooseFile(id) {
  const tool = currentTool();
  if (tool && tool.inputs === "one") {
    // Radio behaviour: one input means one file, so picking replaces.
    state.selected = [id];
  } else {
    const at = state.selected.indexOf(id);
    if (at === -1) state.selected.push(id);
    else state.selected.splice(at, 1);
  }
  renderFiles();
  updateRun();
}

function previewFile(id) {
  if (state.active === id) return;
  state.active = id;
  state.sequence = [];
  syncFieldFromPages();
  renderFiles();
  renderPages();
}

function renderFiles() {
  ui.filerail.textContent = "";

  state.files.forEach((file) => {
    const position = state.selected.indexOf(file.id);
    const chosen = position !== -1;

    const chip = node("div", "filechip");
    if (file.id === state.active) chip.classList.add("active");
    if (chosen) chip.classList.add("chosen");

    const badge = node("button", "badge");
    badge.type = "button";
    badge.title = chosen ? "Remove from this operation" : "Use in this operation";
    badge.setAttribute("aria-pressed", String(chosen));
    if (chosen) badge.appendChild(node("span", null, String(position + 1)));
    badge.addEventListener("click", (event) => {
      event.stopPropagation();
      chooseFile(file.id);
    });
    chip.appendChild(badge);

    chip.appendChild(node("span", "label", file.name));

    let detail = humanSize(file.size);
    let detailClass = "count";
    if (file.error) {
      detail = "unreadable";
      detailClass = "count locked";
    } else if (file.encrypted) {
      detail = "locked";
      detailClass = "count locked";
    } else if (file.pages != null) {
      detail = `${file.pages}p`;
    }
    chip.appendChild(node("span", detailClass, detail));

    const drop = node("button", "drop", "×");
    drop.type = "button";
    drop.title = `Remove ${file.name}`;
    drop.addEventListener("click", (event) => {
      event.stopPropagation();
      removeFile(file.id);
    });
    chip.appendChild(drop);

    chip.addEventListener("click", () => previewFile(file.id));
    ui.filerail.appendChild(chip);
  });
}

/* ═══════════════════════════════════════════════════════════════════ pages */

let thumbnailWatcher = null;

function renderPages() {
  ui.pagegrid.textContent = "";
  const file = activeFile();
  if (!file) { ui.pagehint.textContent = ""; return; }

  if (thumbnailWatcher) thumbnailWatcher.disconnect();
  thumbnailWatcher = new IntersectionObserver(onThumbnailVisible, { rootMargin: "300px" });

  const total = file.pages || 1;
  const field = pageField();
  const chosen = new Set(state.sequence);

  ui.pagehint.textContent = describePages(file, field);

  for (let number = 1; number <= total; number += 1) {
    const card = node("button", "page");
    card.type = "button";
    card.dataset.page = String(number);
    if (field) card.classList.add("selectable");
    if (chosen.has(number)) card.classList.add("chosen");

    const sheet = node("div", "sheet");
    if (state.previews && !file.encrypted && !file.error) {
      const image = new Image();
      image.alt = `Page ${number}`;
      image.loading = "lazy";
      image.dataset.src = `/api/files/${file.id}/page/${number - 1}?width=240`;
      sheet.appendChild(image);
      thumbnailWatcher.observe(image);
    } else {
      sheet.appendChild(node("span", "placeholder", String(number)));
    }

    const tick = node("span", "tick");
    tick.appendChild(icon(CHECK, 11));
    sheet.appendChild(tick);
    // The check itself is revealed by CSS only on .chosen; an unselected page
    // showing a tick reads as already selected.

    card.appendChild(sheet);
    card.appendChild(node("span", "num", labelFor(number, field)));

    if (field) card.addEventListener("click", () => togglePage(number));
    else card.disabled = true;

    ui.pagegrid.appendChild(card);
  }
}

function labelFor(number, field) {
  if (fieldIsOrdered(field)) {
    const at = state.sequence.indexOf(number);
    if (at !== -1) return `${at + 1} ← p${number}`;
  }
  return String(number);
}

function describePages(file, field) {
  if (file.encrypted) return "Locked — enter the password below to work on this file.";
  if (file.error) return file.error;
  if (!field) {
    const count = `${file.pages || 0} page${file.pages === 1 ? "" : "s"}`;
    return currentTool()
      ? `${file.name} · ${count}`
      : `${file.name} · ${count} — choose a tool above to get started.`;
  }
  if (!state.sequence.length) {
    return fieldIsOrdered(field)
      ? "Click pages in the order you want them."
      : "Click pages to select them, or type a range below.";
  }
  const count = state.sequence.length;
  return `${count} page${count === 1 ? "" : "s"} selected — ${
    fieldIsOrdered(field) ? state.sequence.join(",") : formatRange(state.sequence)
  }`;
}

function onThumbnailVisible(entries, observer) {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    const image = entry.target;
    observer.unobserve(image);
    image.addEventListener("error", () => {
      // Previews are a nicety; a failure must not break the page.
      const sheet = image.parentElement;
      if (sheet) { image.remove(); sheet.prepend(node("span", "placeholder", "·")); }
    }, { once: true });
    image.src = image.dataset.src;
  }
}

function togglePage(number) {
  const at = state.sequence.indexOf(number);
  if (at === -1) state.sequence.push(number);
  else state.sequence.splice(at, 1);

  syncFieldFromPages();
  repaintPages();
  updateRun();
}

/** Write the page selection into the tool's range field. */
function syncFieldFromPages() {
  const field = pageField();
  if (!field) return;
  const input = ui.form.querySelector(`[name="${field.name}"]`);
  if (!input) return;
  input.value = fieldIsOrdered(field)
    ? state.sequence.join(",")
    : formatRange(state.sequence);
}

/** Read the range field back into the page selection, after typing. */
function syncPagesFromField() {
  const field = pageField();
  const file = activeFile();
  if (!field || !file) return;
  const input = ui.form.querySelector(`[name="${field.name}"]`);
  if (!input) return;

  state.sequence = fieldIsOrdered(field)
    ? input.value.split(",").map((v) => parseInt(v, 10)).filter((v) => v >= 1 && v <= (file.pages || 1))
    : [...parseRange(input.value, file.pages || 1)].sort((a, b) => a - b);
  repaintPages();
}

/** Update selection classes without re-requesting a single thumbnail. */
function repaintPages() {
  const field = pageField();
  const chosen = new Set(state.sequence);
  ui.pagegrid.querySelectorAll(".page").forEach((card) => {
    const number = Number(card.dataset.page);
    card.classList.toggle("chosen", chosen.has(number));
    const label = card.querySelector(".num");
    if (label) label.textContent = labelFor(number, field);
  });
  const file = activeFile();
  if (file) ui.pagehint.textContent = describePages(file, field);
}

/* ═══════════════════════════════════════════════════════════ tabs & tools */

const groups = () => [...new Set(state.tools.map((t) => t.group))];

/** Build the whole bar: one tab per category, each opening a menu of tools.
 *
 * Opening is CSS-driven (`:hover` and `:focus-within`) so a pointer and a
 * keyboard reach the menu the same way, with no open/closed state to keep in
 * sync here.
 */
function renderNav() {
  ui.navtabs.textContent = "";

  groups().forEach((name) => {
    const group = node("div", "navgroup");

    const tools = state.tools.filter((tool) => tool.group === name);
    const holding = tools.some((tool) => tool.id === state.tool);

    const tab = node("button", `tab${holding ? " holding" : ""}`, name);
    tab.type = "button";
    tab.setAttribute("aria-haspopup", "true");
    group.appendChild(tab);

    const menu = node("div", "menu");
    menu.setAttribute("role", "menu");
    menu.setAttribute("aria-label", name);

    tools.forEach((tool) => {
      const item = node("button", "tool", tool.label);
      item.type = "button";
      item.setAttribute("role", "menuitem");
      item.title = tool.description;
      item.setAttribute("aria-pressed", String(state.tool === tool.id));
      item.addEventListener("click", () => selectTool(tool.id));
      menu.appendChild(item);
    });

    group.appendChild(menu);
    ui.navtabs.appendChild(group);
  });
}

function selectTool(id) {
  state.tool = id;
  state.sequence = [];
  const tool = currentTool();

  // A one-input tool cannot act on three files; keep the first chosen.
  if (tool && tool.inputs === "one" && state.selected.length > 1) {
    state.selected = [state.selected[0]];
  }
  if (tool && tool.inputs === "one" && state.selected.length === 1) {
    state.active = state.selected[0];
  }

  const panelWasHidden = ui.panel.classList.contains("hidden");

  renderNav();
  renderPanel();
  renderFiles();
  renderPages();
  updateRun();
  setStatus("");
  ui.results.textContent = "";

  // Arriving for the first time, the card announces itself rather than
  // shoving the document down without explanation.
  if (MOTION_OK && panelWasHidden && !ui.panel.classList.contains("hidden")) {
    ui.panel.animate(
      [{ opacity: 0, transform: "translateY(-10px)" }, { opacity: 1, transform: "none" }],
      { duration: 300, easing: "cubic-bezier(.22, .9, .28, 1)" },
    );
  }

  // Moving focus out of the menu is what shuts it, and it also puts a keyboard
  // user straight into the options they just asked for.
  const landed = ui.panel.querySelector("input, select") || ui.run;
  if (landed && !ui.workspace.classList.contains("hidden")) {
    landed.focus({ preventScroll: true });
  } else if (document.activeElement instanceof HTMLElement) {
    document.activeElement.blur();
  }
}

/* ═══════════════════════════════════════════════════════════════════ panel */

function renderPanel() {
  const tool = currentTool();
  ui.form.textContent = "";

  if (!tool) { ui.panel.classList.add("hidden"); return; }
  ui.panel.classList.remove("hidden");
  ui.panelTitle.textContent = tool.label;
  ui.panelDesc.textContent = tool.description;

  // Checkboxes go in their own full-width row at the end. Mixed into the
  // grid they align against whichever neighbour has the tallest help text,
  // which never looks deliberate.
  const toggles = tool.fields.filter((f) => f.kind === "bool");
  const inputs = tool.fields.filter((f) => f.kind !== "bool");

  inputs.forEach((field) => ui.form.appendChild(buildField(field)));
  if (toggles.length) {
    const row = node("div", "toggles");
    toggles.forEach((field) => row.appendChild(buildField(field)));
    ui.form.appendChild(row);
  }
  applyConditions();
}

function buildField(field) {
  const wrapper = node("div", `field ${field.kind}`);
  wrapper.dataset.name = field.name;
  const controlId = `field-${field.name}`;

  if (field.kind === "bool") {
    wrapper.className = "field checkbox";
    wrapper.dataset.name = field.name;
    const input = document.createElement("input");
    input.type = "checkbox";
    input.id = controlId;
    input.name = field.name;
    input.checked = Boolean(field.default);
    input.addEventListener("change", applyConditions);
    wrapper.append(input, labelFor2(controlId, field.label));
    return wrapper;
  }

  wrapper.appendChild(labelFor2(controlId, field.label + (field.required ? " *" : "")));

  if (field.kind === "select") {
    const select = document.createElement("select");
    select.id = controlId;
    select.name = field.name;
    (field.choices || []).forEach((choice) => {
      const option = document.createElement("option");
      option.value = choice;
      option.textContent = choice;
      if (String(field.default) === String(choice)) option.selected = true;
      select.appendChild(option);
    });
    select.addEventListener("change", applyConditions);
    wrapper.appendChild(select);
  } else if (field.kind === "multiselect") {
    const set = node("div", "chipset");
    const defaults = field.default || [];
    (field.choices || []).forEach((choice) => {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.name = field.name;
      input.value = choice;
      input.checked = defaults.includes(choice);
      label.append(input, document.createTextNode(choice));
      set.appendChild(label);
    });
    wrapper.appendChild(set);
  } else {
    const input = document.createElement("input");
    input.id = controlId;
    input.name = field.name;
    input.type = field.kind === "number" ? "number"
      : field.kind === "password" ? "password" : "text";
    if (field.default !== null && field.default !== undefined) {
      input.value = String(field.default);
    }
    if (field.min != null) input.min = field.min;
    if (field.max != null) input.max = field.max;
    if (field.kind === "pages") {
      input.placeholder = "1-3,7 · last · odd";
      input.addEventListener("input", syncPagesFromField);
    }
    input.addEventListener("input", updateRun);
    wrapper.appendChild(input);
  }

  if (field.help) wrapper.appendChild(node("span", "help", field.help));
  return wrapper;
}

function labelFor2(id, text) {
  const label = document.createElement("label");
  label.htmlFor = id;
  label.textContent = text;
  return label;
}

/** Hide fields whose `when` condition is not satisfied. */
function applyConditions() {
  const tool = currentTool();
  if (!tool) return;
  const values = readOptions();

  tool.fields.forEach((field) => {
    if (!field.when) return;
    const wrapper = ui.form.querySelector(`[data-name="${field.name}"]`);
    if (!wrapper) return;
    const satisfied = Object.entries(field.when).every(([key, allowed]) =>
      allowed.map(String).includes(String(values[key]))
    );
    wrapper.classList.toggle("hidden", !satisfied);
  });

  repaintPages();
  updateRun();
}

function readOptions() {
  const tool = currentTool();
  const options = {};
  if (!tool) return options;

  tool.fields.forEach((field) => {
    if (field.kind === "multiselect") {
      options[field.name] = Array.from(
        ui.form.querySelectorAll(`input[name="${field.name}"]:checked`)
      ).map((input) => input.value);
      return;
    }
    const control = ui.form.querySelector(`[name="${field.name}"]`);
    if (!control) return;
    options[field.name] = field.kind === "bool" ? control.checked : control.value;
  });
  return options;
}

/* ═════════════════════════════════════════════════════════════════════ run */

function requirementMessage() {
  const tool = currentTool();
  if (!tool) return "Pick a tool above.";

  const count = state.selected.length;
  if (tool.inputs === "one" && count !== 1) return "Choose one file.";
  if (tool.inputs === "two" && count !== 2) {
    return `Choose two files: the document, then the ${tool.second_label.toLowerCase()}.`;
  }
  if (tool.inputs === "many") {
    const least = tool.id === "merge" ? 2 : 1;
    if (count < least) return `Choose at least ${least === 2 ? "two files" : "one file"}.`;
  }

  const values = readOptions();
  const missing = tool.fields.filter((field) => {
    if (!field.required) return false;
    const wrapper = ui.form.querySelector(`[data-name="${field.name}"]`);
    if (wrapper && wrapper.classList.contains("hidden")) return false;
    const value = values[field.name];
    return value === undefined || value === null || String(value).trim() === "";
  });

  if (missing.length) return `Still needed: ${missing.map((f) => f.label).join(", ")}.`;
  return "";
}

function updateRun() {
  const message = requirementMessage();
  ui.run.disabled = Boolean(message);
  ui.requirement.textContent = message;
}

async function runTool() {
  const tool = currentTool();
  if (!tool) return;

  ui.run.disabled = true;
  ui.results.textContent = "";
  setStatus(`Running ${tool.label.toLowerCase()}…`, "working");

  try {
    const data = await api("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tool: tool.id,
        files: state.selected,
        options: readOptions(),
      }),
    });
    setStatus("");
    renderResults(data);
    ui.results.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    updateRun();
  }
}

function renderResults(data) {
  ui.results.textContent = "";
  const card = node("div", "result-card");

  const head = node("div");
  head.appendChild(node("p", "result-summary", data.summary));
  if (data.input_bytes && data.output_bytes) {
    head.appendChild(node("p", "result-delta", data.size_delta));
  }
  card.appendChild(head);

  const downloads = node("div", "downloads");
  const many = data.outputs.length > 1;

  if (many) {
    const zip = document.createElement("a");
    zip.className = "download primary";
    zip.href = `/api/result/${data.job}/archive/all.zip`;
    zip.download = "recto-results.zip";
    zip.append(icon("M8 2v9m0 0L4.5 7.5M8 11l3.5-3.5M2.5 13.5h11", 13),
               node("span", "name", `Download all ${data.outputs.length}`));
    downloads.appendChild(zip);
  }

  data.outputs.forEach((output, index) => {
    const link = document.createElement("a");
    link.className = many ? "download" : "download primary";
    link.href = `/api/result/${data.job}/${output.index}`;
    link.download = output.name;
    link.append(
      icon("M8 2v9m0 0L4.5 7.5M8 11l3.5-3.5M2.5 13.5h11", 13),
      node("span", "name", output.name),
      node("span", "size", humanSize(output.bytes)),
    );
    if (index < 24) downloads.appendChild(link);
  });

  if (data.outputs.length > 24) {
    downloads.appendChild(node("span", "size", `and ${data.outputs.length - 24} more`));
  }

  card.appendChild(downloads);
  ui.results.appendChild(card);
}

/* ═════════════════════════════════════════════════════════════ transitions */

/** Grow the drop card into the document card.
 *
 * A FLIP: measure where the card is, swap the interface over, measure where
 * the document card landed, then play the second element from the first one's
 * rectangle back to its own. The scale is markedly non-uniform, which is why
 * the card is emptied first — what stretches is blank white, and the contents
 * fade in only once the shape has settled.
 */
async function growCardIntoWorkspace() {
  const from = ui.dropcard.getBoundingClientRect();

  if (MOTION_OK) {
    ui.dropcard.classList.add("emptying");
    await wait(170);
  }

  enterWorkspace();
  renderFiles();
  renderPages();
  updateRun();
  ui.dropcard.classList.remove("emptying");

  if (!MOTION_OK) return;

  const to = ui.doc.getBoundingClientRect();
  if (!to.width || !to.height) return;

  const ease = "cubic-bezier(.22, .9, .28, 1)";
  ui.doc.animate(
    [
      {
        // `transform-origin` has to be the top-left corner. Scaling about the
        // default centre moves the corners too, so the card would begin a
        // couple of hundred pixels from where the drop card actually sat.
        transformOrigin: "0 0",
        transform: `translate(${from.left - to.left}px, ${from.top - to.top}px)`
          + ` scale(${from.width / to.width}, ${from.height / to.height})`,
      },
      { transformOrigin: "0 0", transform: "none" },
    ],
    { duration: 460, easing: ease },
  );

  // `fill: backwards` holds these at opacity 0 through the delay, so the
  // contents stay hidden while the card is still changing shape.
  for (const child of ui.doc.children) {
    child.animate([{ opacity: 0 }, { opacity: 1 }],
      { duration: 300, delay: 250, easing: "ease-out", fill: "backwards" });
  }

  if (!ui.panel.classList.contains("hidden")) {
    ui.panel.animate(
      [{ opacity: 0, transform: "translateY(10px)" }, { opacity: 1, transform: "none" }],
      { duration: 320, delay: 300, easing: ease, fill: "backwards" },
    );
  }
}

/* ══════════════════════════════════════════════════════════════════ states */

function enterWorkspace() {
  ui.landing.classList.add("hidden");
  ui.workspace.classList.remove("hidden");
  ui.navbar.classList.add("in");
  ui.restart.classList.remove("invisible");
  // No tool is picked on the user's behalf: until they choose one from the
  // bar, the files are all there is to see.
}

function leaveWorkspace() {
  ui.workspace.classList.add("hidden");
  ui.navbar.classList.remove("in");
  ui.restart.classList.add("invisible");
  ui.landing.classList.remove("hidden");
  ui.results.textContent = "";
  setStatus("");
}

async function startOver() {
  const ids = state.files.map((f) => f.id);

  if (MOTION_OK) {
    const leaving = ui.workspace.animate(
      [{ opacity: 1 }, { opacity: 0, transform: "translateY(12px) scale(.985)" }],
      { duration: 240, easing: "ease-in", fill: "forwards" },
    );
    ui.navbar.classList.remove("in");
    await leaving.finished;
    leaving.cancel();
  }

  state.files = [];
  state.selected = [];
  state.active = null;
  state.sequence = [];
  state.tool = null;
  renderNav();
  renderPanel();
  leaveWorkspace();

  if (MOTION_OK) {
    ui.landing.animate(
      [{ opacity: 0, transform: "scale(.96)" }, { opacity: 1, transform: "none" }],
      { duration: 340, easing: "cubic-bezier(.22, .9, .28, 1)" },
    );
  }
  await Promise.all(
    ids.map((id) => api(`/api/files/${id}`, { method: "DELETE" }).catch(() => {}))
  );
}

/* Publish the bar's height so the workspace can clear it. Measured rather
   than assumed, because the bar wraps to two rows on a narrow screen. */
function publishBarHeight() {
  const height = ui.navbar.getBoundingClientRect().height;
  if (height) document.documentElement.style.setProperty("--bar-h", `${height}px`);
}

new ResizeObserver(publishBarHeight).observe(ui.navbar);

/* ═════════════════════════════════════════════════════════════════ wiring */

ui.dropcard.addEventListener("click", () => ui.picker.click());
ui.dropcard.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    ui.picker.click();
  }
});
ui.addmore.addEventListener("click", () => ui.picker.click());
ui.restart.addEventListener("click", startOver);

ui.picker.addEventListener("change", () => {
  addFiles(ui.picker.files);
  ui.picker.value = "";
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  const active = document.activeElement;
  if (active instanceof HTMLElement && active.closest(".navgroup")) active.blur();
});

ui.run.addEventListener("click", runTool);
ui.form.addEventListener("input", updateRun);
ui.form.addEventListener("submit", (event) => event.preventDefault());

/* Dropping anywhere in the window works, not just on the card. */
let dragDepth = 0;

/** Signal that a drop is being offered.
 *
 * On the landing screen the card itself is the target, so it fills and its
 * label changes. Once files are loaded the card is gone, so a full-window
 * veil stands in for it.
 */
function setDragging(on) {
  const title = ui.dropcard.querySelector(".dropcard-title");
  const onLanding = !ui.landing.classList.contains("hidden");

  ui.dropcard.classList.toggle("dragging", on && onLanding);
  ui.dropveil.classList.toggle("on", on && !onLanding);

  if (title) {
    title.textContent = on && onLanding
      ? title.dataset.active
      : title.dataset.idle;
  }
}

window.addEventListener("dragenter", (event) => {
  event.preventDefault();
  dragDepth += 1;
  if (event.dataTransfer && [...event.dataTransfer.types].includes("Files")) {
    setDragging(true);
  }
});

window.addEventListener("dragover", (event) => event.preventDefault());

window.addEventListener("dragleave", (event) => {
  event.preventDefault();
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) setDragging(false);
});

window.addEventListener("drop", (event) => {
  event.preventDefault();
  dragDepth = 0;
  setDragging(false);
  addFiles(event.dataTransfer && event.dataTransfer.files);
});

(async function start() {
  try {
    const data = await api("/api/tools");
    state.tools = data.tools;
    state.previews = data.previews !== false;
    state.group = groups()[0];
    renderNav();
  } catch (error) {
    setStatus(`Could not reach the Recto server: ${error.message}`, "error");
  }
})();
