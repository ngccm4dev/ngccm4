/* NGCCM4 benchmark site. Plain JS, no dependencies; data comes from data/data.js. */
(function () {
  "use strict";
  const DATA = window.NGCCM4_DATA;
  if (!DATA) { document.body.textContent = "data/data.js failed to load."; return; }

  const $ = (sel, el) => (el || document).querySelector(sel);
  const el = (tag, attrs, children) => {
    const node = document.createElement(tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k === "html") node.innerHTML = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined) node.setAttribute(k, v);
    }
    if (children) for (const c of [].concat(children)) if (c !== null && c !== undefined) node.append(c);
    return node;
  };
  const fmt = (n) => (n === null || n === undefined) ? "" : Number(n).toLocaleString("en-US");
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const inlineCode = (s) => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>");

  const CATS = { kem: "KEM", kex: "Key exchange", sig: "Signatures" };
  const STATUS_ORDER = { measured: 0, partial: 1, failed: 2, pending: 3, "not-run": 4 };
  const STATUS_LABEL = { measured: "measured", partial: "partial", failed: "failed", pending: "not yet run", "not-run": "not run" };
  const STATUS_CLASS = { measured: "good", partial: "warning", failed: "critical", pending: "neutral", "not-run": "neutral" };
  const STATUS_HINT = { pending: "board-tier implementation that has not been benchmarked yet", "not-run": "QEMU-tier implementation: not attempted on the board" };
  const KAT_ORDER = { match: 0, mismatch: 1, "run-failed": 2, timeout: 3, "not-checked": 4 };
  const KAT_CLASS = { match: "good", mismatch: "serious", "run-failed": "critical", timeout: "critical", "not-checked": "neutral" };
  const FAILURE_LABEL = {
    hardfault: "HardFault on the board (heap or stack beyond the 640 KB SRAM)",
    timeout: "Timeout (10 minute cap per operation)",
    "link-overflow": "Link failed: image does not fit the 640 KB SRAM",
    "ram-qemu-evidence": "Not attempted: needed more than 4 MiB RAM in the QEMU KAT run",
    hangs: "Not run: hangs on the board at the first iteration",
    "too-slow": "Not run: too slow for the board (more than the run budget)",
    partial: "Partial: some operations never returned",
    other: "Other",
  };
  const GROUPS = ["cycles", "sizes", "code", "stack", "kat"];
  const LEVELS = ["128", "192", "256", "384", "512"];
  const GROUP_LABEL = { cycles: "Cycles", sizes: "Sizes", code: "Code size", stack: "Stack", kat: "KAT" };

  const rowsById = {};
  for (const cat of Object.keys(DATA.categories)) for (const r of DATA.categories[cat].rows) rowsById[r.id] = r;

  // ------------------------------------------------------------------ state <-> URL hash
  const state = {
    tab: "kem", sort: null, dir: "asc", q: "", impl: new Set(["ref", "m4"]),
    status: new Set(["measured", "partial"]), level: new Set(), groups: new Set(GROUPS),
    bars: "linear", stat: "avg", open: new Set(),
  };
  function readHash() {
    const h = location.hash.replace(/^#/, "");
    if (!h) return;
    const [tab, qs] = h.split("?");
    if (tab) state.tab = tab;
    const p = new URLSearchParams(qs || "");
    if (p.has("sort")) state.sort = p.get("sort");
    if (p.has("dir")) state.dir = p.get("dir") === "desc" ? "desc" : "asc";
    if (p.has("q")) state.q = p.get("q");
    if (p.has("impl")) state.impl = new Set(p.get("impl").split(",").filter(Boolean));
    if (p.has("status")) state.status = new Set(p.get("status").split(",").filter(Boolean));
    if (p.has("level")) state.level = new Set(p.get("level").split(",").filter(Boolean));
    if (p.has("groups")) state.groups = new Set(p.get("groups").split(",").filter(Boolean));
    if (p.has("bars")) state.bars = p.get("bars");
    if (p.has("stat")) state.stat = p.get("stat");
    if (p.has("open")) state.open = new Set(p.get("open").split(",").filter(Boolean));
  }
  function writeHash() {
    const p = new URLSearchParams();
    if (state.tab in CATS) {
      if (state.sort) { p.set("sort", state.sort); p.set("dir", state.dir); }
      if (state.q) p.set("q", state.q);
      if (state.impl.size !== 2) p.set("impl", [...state.impl].join(","));
      if (!(state.status.size === 2 && state.status.has("measured") && state.status.has("partial"))) p.set("status", [...state.status].join(","));
      if (state.level.size) p.set("level", [...state.level].join(","));
      if (state.groups.size !== GROUPS.length) p.set("groups", [...state.groups].join(","));
      if (state.bars !== "linear") p.set("bars", state.bars);
      if (state.stat !== "avg") p.set("stat", state.stat);
      const open = [...state.open].filter((id) => rowsById[id] && rowsById[id].category === state.tab);
      if (open.length) p.set("open", open.join(","));
    }
    const qs = p.toString();
    const next = "#" + state.tab + (qs ? "?" + qs : "");
    if (location.hash === next) return;
    try { history.replaceState(null, "", next); } catch (e) { location.hash = next.slice(1); }
  }

  // ------------------------------------------------------------------ columns
  function naReason(row, op) {
    if (!row.expected_ops.includes(op)) {
      const n = row.sizes && row.sizes.passes;
      return n !== undefined && n !== null ? `not applicable: ${n}-pass scheme` : "not applicable";
    }
    if (row.status_text) return "not measured: " + row.status_text;
    return row.run_status === "not-run" ? "not run on the board (QEMU-tier implementation)" : row.run_status === "pending" ? "not benchmarked yet" : "not measured";
  }
  function cycleTitle(row, op) {
    const c = row.cycles[op];
    if (!c) return naReason(row, op);
    return `${op}: avg ${fmt(c.avg)}, median ${fmt(c.median)}, min ${fmt(c.min)}, max ${fmt(c.max)} cycles (${c.count} iteration${c.count === 1 ? "" : "s"})`;
  }
  function sizeCols(cat) {
    const S = (key, label, title) => ({ key: "sz_" + key, label, group: "sizes", type: "num", bar: "sizes", unit: "bytes",
      get: (r) => (r.sizes && r.sizes[key] !== undefined) ? r.sizes[key] : null, title: () => title });
    if (cat === "kem") return [S("pk", "pk", "public key bytes"), S("sk", "sk", "secret key bytes"), S("ct", "ct", "ciphertext bytes"), S("ss", "ss", "shared secret bytes")];
    if (cat === "sig") return [S("pk", "pk", "public key bytes"), S("sk", "sk", "secret key bytes"), S("sig_max", "sig", "signature bytes (largest of the KAT counts; the minimum is in the row details)")];
    const cols = [S("pk_a", "pk A", "initiator long-term public key bytes (0 = unauthenticated)"), S("sk_a", "sk A", "initiator secret key bytes"),
      S("pk_b", "pk B", "responder public key bytes"), S("sk_b", "sk B", "responder secret key bytes")];
    const maxPasses = Math.max(0, ...DATA.categories.kex.rows.map((r) => (r.sizes && r.sizes.passes) || 0));
    cols.push({ key: "sz_passes", label: "passes", group: "sizes", type: "num", get: (r) => (r.sizes && r.sizes.passes !== undefined) ? r.sizes.passes : null, title: () => "number of message passes" });
    for (let i = 1; i <= maxPasses; i++) {
      cols.push({ key: "sz_m" + i, label: "M" + i, group: "sizes", type: "num", bar: "sizes", unit: "bytes",
        get: (r) => (r.sizes && r.sizes.msgs && r.sizes.msgs.length >= i) ? r.sizes.msgs[i - 1] : null,
        title: (r) => (r.sizes && r.sizes.msgs && r.sizes.msgs.length >= i) ? `message ${i} bytes` : "not applicable" });
    }
    cols.push(S("msg_total", "msgs total", "total bytes exchanged over all passes"), S("ss", "ss", "shared secret bytes"));
    return cols;
  }
  function columnsFor(cat) {
    const C = DATA.categories[cat];
    const cols = [
      { key: "scheme", label: "Scheme", group: "id", type: "str", get: (r) => r.scheme, sticky: true },
      { key: "impl", label: "Impl", group: "id", type: "str", get: (r) => r.impl },
      { key: "level", label: "Level", group: "id", type: "level", get: (r) => r.level },
      { key: "status", label: "Status", group: "id", type: "status", get: (r) => r.run_status },
    ];
    for (const op of C.ops) cols.push({ key: "cyc_" + op, label: op, group: "cycles", type: "num", bar: "cycles", unit: "cycles",
      get: (r) => r.cycles[op] ? r.cycles[op][state.stat] : null, title: (r) => cycleTitle(r, op) });
    cols.push({ key: "cyc_total", label: "total", group: "cycles", type: "num", bar: "cycles", unit: "cycles",
      get: (r) => r.cycles_total, title: (r) => r.cycles_total === null ? "total is only given when every operation was measured" : "sum of the average cycles of all operations" });
    cols.push(...sizeCols(cat));
    for (const [k, label] of [["text", ".text"], ["data", ".data"], ["bss", ".bss"], ["total", "flash+ram"]]) cols.push({ key: "code_" + k, label, group: "code", type: "num", bar: "code", unit: "bytes",
      get: (r) => r.code ? r.code[k] : null, title: (r) => r.code ? `${label} of the speed ELF, including the benchmark driver and HAL (source: ${r.code.source})` : "ELF not linked for the board" });
    if (cat === "kem") for (const op of C.ops) cols.push({ key: "stk_" + op, label: op, group: "stack", type: "num", bar: "stack", unit: "bytes",
      get: (r) => (r.stack && r.stack[op] !== undefined) ? r.stack[op] : null, title: () => "stack bytes used by " + op + " (stack app, canary method)" });
    cols.push({ key: "kat", label: "KAT", group: "kat", type: "kat", get: (r) => r.kat.status });
    return cols;
  }

  // ------------------------------------------------------------------ filtering / sorting
  function levelKey(r) { return r.level.label; }
  function visibleRows(cat) {
    const q = state.q.trim().toLowerCase();
    return DATA.categories[cat].rows.filter((r) =>
      state.impl.has(r.impl) && state.status.has(r.run_status) &&
      (!state.level.size || state.level.has(levelKey(r))) &&
      (!q || r.scheme.toLowerCase().includes(q) || (r.ngcc.title || "").toLowerCase().includes(q) || r.ngcc.instance.toLowerCase().includes(q)));
  }
  function compareValues(type, a, b) {
    if (type === "level") {
      const ab = a.bits, bb = b.bits;
      if (ab !== null && bb !== null && ab !== bb) return ab - bb;
      if (ab === null && bb !== null) return 1;
      if (bb === null && ab !== null) return -1;
      return (a.param_set || a.label).localeCompare(b.param_set || b.label, undefined, { numeric: true });
    }
    if (type === "status") return STATUS_ORDER[a] - STATUS_ORDER[b];
    if (type === "kat") return KAT_ORDER[a] - KAT_ORDER[b];
    if (type === "num") return a - b;
    return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
  }
  function sortRows(rows, cols) {
    const col = cols.find((c) => c.key === state.sort) || cols[0];
    const dir = state.dir === "desc" ? -1 : 1;
    const keyed = rows.map((r, i) => ({ r, i, v: col.get(r) }));
    keyed.sort((x, y) => {
      const xn = x.v === null || x.v === undefined, yn = y.v === null || y.v === undefined;
      if (xn && yn) return x.i - y.i;
      if (xn) return 1;
      if (yn) return -1;
      const c = compareValues(col.type, x.v, y.v);
      return c !== 0 ? c * dir : (x.r.scheme.localeCompare(y.r.scheme, undefined, { numeric: true }) || x.r.impl.localeCompare(y.r.impl));
    });
    return keyed.map((k) => k.r);
  }
  function barWidth(v, max) {
    if (v === null || v === undefined || v <= 0 || !max) return 0;
    if (state.bars === "log") return max <= 1 ? 100 : Math.max(2, 100 * Math.log10(v + 1) / Math.log10(max + 1));
    return Math.max(0.5, 100 * v / max);
  }

  // ------------------------------------------------------------------ rendering: table
  function badge(cls, label, title) { return el("span", { class: "badge " + cls, title: title || null, text: label }); }
  const LEVEL_SOURCE = {
    name: "level taken from the instance name",
    manifest: "level set in the import manifest",
    spec: "level taken from the submission's specification",
    none: "no security level stated by the submitter",
  };
  function levelCell(lv) {
    const parts = [lv.bits !== null ? `claimed classical security: ${lv.bits} bits` : "security level unknown"];
    if (lv.param_set && lv.param_set !== lv.label) parts.push(`parameter set: ${lv.param_set}`);
    if (lv.variant) parts.push(lv.variant === "f" ? "fast variant" : "small variant");
    if (lv.claim) parts.push(lv.claim);
    parts.push(LEVEL_SOURCE[lv.source] || "source unknown");
    return el("span", { title: parts.join("; "), text: lv.label });
  }
  // link to the submission's algorithm specification, a PDF served from this site (stops the row-toggle click)
  function ngccLink(ngcc, text) {
    if (!ngcc || !ngcc.spec) return null;
    return el("a", { class: "ext" + (text ? " ext-text" : ""), href: ngcc.spec, target: "_blank", rel: "noopener",
      title: `${ngcc.title}: algorithm specification (PDF${ngcc.spec_file ? ", " + ngcc.spec_file : ""})`, text: text || "\u2197",
      onclick: (e) => e.stopPropagation() });
  }
  function schemeCell(r) {
    return el("span", { class: "scheme-name" }, [r.scheme, " ", ngccLink(r.ngcc)]);
  }
  function renderCell(col, row, max) {
    const v = col.get(row);
    const td = el("td", { class: (col.type === "num" ? "num" : "") + (col.bar ? " bar-cell" : "") + (col.sticky ? " sticky" : "") + " col-" + col.group });
    if (col.type === "str") td.textContent = v;
    else if (col.type === "level") td.append(levelCell(v));
    else if (col.type === "status") td.append(badge(STATUS_CLASS[v], STATUS_LABEL[v], row.status_text || STATUS_HINT[v] || "all operations measured"));
    else if (col.type === "kat") td.append(badge(KAT_CLASS[v] || "neutral", v, row.kat.caveat || row.kat.detail || "no KAT check recorded"));
    else {
      td.title = col.title ? col.title(row) : "";
      if (v === null || v === undefined) td.append(el("span", { class: "na", text: "—" }));
      else {
        td.append(document.createTextNode(fmt(v)));
        if (col.bar) td.append(el("span", { class: "bar-track" }, el("span", { class: "bar " + col.bar, style: "width:" + barWidth(v, max).toFixed(2) + "%" })));
      }
    }
    return td;
  }
  function renderDetails(row, cols) {
    const c = DATA.categories[row.category];
    const sections = [];
    const about = el("div", null, [el("h4", { text: "Submission" }), el("div", { html:
      (row.ngcc.spec ? `<a class="ext-text" href="${esc(row.ngcc.spec)}" target="_blank" rel="noopener" title="algorithm specification (PDF)"><b>${esc(row.ngcc.title)}</b> \u2197</a>` : `<b>${esc(row.ngcc.title)}</b>`) +
      ` &middot; instance <code>${esc(row.ngcc.instance)}</code>` +
      (row.ngcc.pub_date ? ` &middot; published ${esc(row.ngcc.pub_date)}` : "") +
      (row.ngcc.spec ? ` &middot; <a href="${esc(row.ngcc.spec)}" target="_blank" rel="noopener">specification (PDF)</a>` : "") +
      (row.ngcc.spec_extra || []).map((x) => ` &middot; <a href="${esc(x.href)}" target="_blank" rel="noopener" title="${esc(x.file)}">${esc(x.file.replace(/\.pdf$/i, ""))}</a>`).join("") +
      (row.ngcc.zip_url ? ` &middot; <a href="${esc(row.ngcc.zip_url)}" rel="noopener" title="original submission package (NGCC download)">submission zip</a>` : "") +
      (row.ngcc.comments_url ? ` &middot; <a href="${esc(row.ngcc.comments_url)}" target="_blank" rel="noopener" title="public-comment thread on the NGCC mailing list">public comments</a>` : "") +
      `<br>Directory <code>${esc(row.family)}/${esc(row.scheme)}/${esc(row.impl)}</code> &middot; tier <b>${esc(row.tier)}</b>` +
      (row.hand_ported ? " &middot; hand-ported" : " &middot; imported reference code") })]);
    sections.push(about);
    const st = el("div", null, [el("h4", { text: "Board run" })]);
    st.append(el("div", null, [badge(STATUS_CLASS[row.run_status], STATUS_LABEL[row.run_status]), " ",
      el("span", { class: "note", text: row.status_text || (row.run_status === "measured" ? "every operation completed" : STATUS_HINT[row.run_status] || "") })]));
    if (row.failure_kind) st.append(el("div", { class: "note", text: "Category: " + (FAILURE_LABEL[row.failure_kind] || row.failure_kind) }));
    if (Object.keys(row.cycles).length) {
      const t = el("table", null, el("tr", null, [el("th", { text: "op" }), ...["avg", "median", "min", "max", "count"].map((k) => el("th", { text: k, style: "text-align:right" }))]));
      for (const op of row.expected_ops) if (row.cycles[op]) t.append(el("tr", null, [el("th", { text: op }), ...["avg", "median", "min", "max", "count"].map((k) => el("td", { text: fmt(row.cycles[op][k]) }))]));
      st.append(t);
    }
    sections.push(st);
    const sz = el("div", null, [el("h4", { text: "Sizes" })]);
    if (row.sizes) {
      const src = { kat_raw: "measured from the benchmarked binary (testvectors dump on QEMU)", ngcc_results: "host build of the same reference code", kat: "official NGCC KAT file" }[row.sizes.source] || row.sizes.source;
      const items = Object.entries(row.sizes).filter(([k]) => !["source", "kat_path", "results_path", "msgs"].includes(k)).map(([k, v]) => `${k} = ${fmt(v)}`);
      if (row.sizes.msgs) items.push("messages = [" + row.sizes.msgs.map(fmt).join(", ") + "]");
      sz.append(el("div", { text: items.join(", ") + " bytes" }), el("div", { class: "note", text: "Source: " + src + (row.sizes.kat_path ? "; official KAT file " + row.sizes.kat_path : "") }));
    } else sz.append(el("div", { class: "note", text: "no key sizes available" }));
    if (row.code) sz.append(el("div", { class: "note", text: `Code size: .text ${fmt(row.code.text)}, .data ${fmt(row.code.data)}, .bss ${fmt(row.code.bss)} (speed ELF, includes driver and HAL; source: ${row.code.source})` }));
    sections.push(sz);
    const kat = el("div", null, [el("h4", { text: "KAT check (QEMU)" }), el("div", null, [badge(KAT_CLASS[row.kat.status] || "neutral", row.kat.status), " ", el("span", { class: "note", text: row.kat.detail })])]);
    if (row.kat.caveat) kat.append(el("div", { class: "note", text: "Caveat: " + row.kat.caveat }));
    if (row.notes.length) kat.append(el("h4", { text: "Notes", style: "margin-top:8px" }), el("ul", null, row.notes.map((n) => el("li", { text: n }))));
    sections.push(kat);
    return el("tr", { class: "details" }, el("td", { colspan: cols.length }, el("div", { class: "details-grid" }, sections)));
  }
  function renderTable() {
    const cat = state.tab;
    const cols = columnsFor(cat);
    if (!cols.some((c) => c.key === state.sort)) { state.sort = cols[0].key; state.dir = "asc"; }
    const rows = sortRows(visibleRows(cat), cols);
    const table = $("#table");
    table.className = "data " + GROUPS.filter((g) => !state.groups.has(g)).map((g) => "hide-" + g).join(" ") + (state.bars === "off" ? " bars-off" : "");
    table.innerHTML = "";
    const thead = el("thead");
    const grpRow = el("tr", { class: "groups" });
    let i = 0;
    while (i < cols.length) {
      let j = i; while (j < cols.length && cols[j].group === cols[i].group) j++;
      const g = cols[i].group;
      grpRow.append(el("th", { colspan: j - i, class: "col-" + g + (cols[i].sticky ? " sticky" : ""), text: g === "id" ? "" : (g === "cycles" ? `cycles (${state.stat})` : g === "sizes" ? "sizes (bytes)" : g === "code" ? "code size (bytes)" : g === "stack" ? "stack (bytes)" : "") }));
      i = j;
    }
    const colRow = el("tr", { class: "cols" });
    for (const col of cols) {
      const th = el("th", { class: (col.type === "num" ? "num" : "") + (col.sticky ? " sticky" : "") + " col-" + col.group, text: col.label, title: "sort by " + col.label });
      if (col.key === state.sort) th.setAttribute("aria-sort", state.dir === "desc" ? "descending" : "ascending");
      th.addEventListener("click", () => {
        if (state.sort === col.key) state.dir = state.dir === "asc" ? "desc" : "asc";
        else { state.sort = col.key; state.dir = col.type === "num" ? "asc" : "asc"; }
        render();
      });
      colRow.append(th);
    }
    thead.append(grpRow, colRow);
    const maxes = {};
    for (const col of cols) if (col.bar) maxes[col.key] = Math.max(0, ...rows.map((r) => col.get(r)).filter((v) => typeof v === "number"));
    const tbody = el("tbody");
    for (const r of rows) {
      const tr = el("tr", { class: (r.run_status === "measured" ? "" : "muted") + (state.open.has(r.id) ? " open" : ""), "data-id": r.id });
      for (const col of cols) {
        const td = renderCell(col, r, maxes[col.key]);
        if (col.key === "scheme") { td.classList.add("scheme"); td.title = "show details"; td.textContent = ""; td.append(schemeCell(r)); td.addEventListener("click", () => { state.open.has(r.id) ? state.open.delete(r.id) : state.open.add(r.id); render(); }); }
        tr.append(td);
      }
      tbody.append(tr);
      if (state.open.has(r.id)) tbody.append(renderDetails(r, cols));
    }
    table.append(thead, tbody);
    const all = DATA.categories[cat].rows.length;
    $("#row-count").textContent = `${rows.length} of ${all} implementations`;
    $("#table-hint").innerHTML = `Click a scheme for details. Click a header to sort; missing values sort last. Bars are scaled to the largest value visible in each column (${state.bars === "log" ? "log scale" : state.bars === "linear" ? "linear" : "hidden"}). Hover a value for min/median/max and iteration count.` +
      (cat === "sig" ? " Signature schemes ran with 1 iteration per operation unless stated otherwise; rejection-sampling schemes vary by about 1% between iterations." : "") +
      (cat === "kex" ? " KEX operations: init (key generation) for A and B, numbered message passes alternating A/B, and shared-secret derivation for A and B." : "");
    window.__lastTable = { cols, rows };
  }

  // ------------------------------------------------------------------ toolbar
  function chip(label, pressed, onclick, title) {
    return el("button", { class: "chip", type: "button", "aria-pressed": pressed ? "true" : "false", title: title || null, text: label, onclick });
  }
  function renderToolbar() {
    const cat = state.tab;
    const rows = DATA.categories[cat].rows;
    const implBox = $("#impl-chips"); implBox.innerHTML = "";
    for (const impl of ["ref", "m4"]) {
      const n = rows.filter((r) => r.impl === impl).length;
      if (!n) continue;
      implBox.append(chip(`${impl} (${n})`, state.impl.has(impl), () => { toggle(state.impl, impl); render(); }, impl === "m4" ? "Cortex-M4 optimised implementation: the submitter's own M4 port imported from the NGCC package, or a hand-written port (DKEM, ZEN, DKEX, ADKEX)" : "reference C implementation"));
    }
    const stBox = $("#status-chips"); stBox.innerHTML = "";
    for (const s of ["measured", "partial", "failed", "pending", "not-run"]) {
      const n = rows.filter((r) => r.run_status === s).length;
      if (!n) continue;
      stBox.append(chip(`${STATUS_LABEL[s]} (${n})`, state.status.has(s), () => { toggle(state.status, s); render(); }));
    }
    const lvBox = $("#level-chips"); lvBox.innerHTML = "";
    const present = new Set(rows.map(levelKey));
    const labels = [...LEVELS, ...[...present].filter((l) => !LEVELS.includes(l)).sort()];
    for (const label of labels) {
      const n = rows.filter((r) => levelKey(r) === label).length;
      if (!n && !LEVELS.includes(label)) continue;
      lvBox.append(chip(`${label} (${n})`, state.level.has(label), () => { toggle(state.level, label); render(); },
        label === "-" ? "no security level stated by the submitter" : `claimed classical security of ${label} bits`));
    }
    if (state.level.size) lvBox.append(chip("clear", false, () => { state.level.clear(); render(); }));
    const gBox = $("#group-chips"); gBox.innerHTML = "";
    for (const g of GROUPS) {
      if (g === "stack" && cat !== "kem") continue;
      gBox.append(chip(GROUP_LABEL[g], state.groups.has(g), () => { toggle(state.groups, g); render(); }));
    }
    $("#search").value = state.q;
    $("#stat-select").value = state.stat;
    $("#bars-select").value = state.bars;
  }
  function toggle(set, v) { set.has(v) ? set.delete(v) : set.add(v); }

  function downloadCsv() {
    const { cols, rows } = window.__lastTable || {};
    if (!cols) return;
    const vis = cols.filter((c) => c.group === "id" || state.groups.has(c.group));
    const head = vis.map((c) => c.group === "id" ? c.label : `${c.group}_${c.label}`.replace(/\s+/g, "_"));
    const lines = [head.join(",")];
    for (const r of rows) lines.push(vis.map((c) => {
      const v = c.get(r);
      if (v === null || v === undefined) return "";
      if (c.type === "level") return v.label;
      return typeof v === "number" ? String(v) : '"' + String(v).replace(/"/g, '""') + '"';
    }).join(","));
    const blob = new Blob([lines.join("\n") + "\n"], { type: "text/csv" });
    const a = el("a", { href: URL.createObjectURL(blob), download: `ngccm4-${state.tab}-${DATA.meta.generated_on}.csv` });
    document.body.append(a); a.click(); a.remove();
  }

  // ------------------------------------------------------------------ not-benchmarked panel
  function miniTable(columns, rows, sortKey) {
    // a small self-contained sortable table (independent of the main state)
    const wrap = el("div", { class: "table-scroll" });
    const table = el("table", { class: "data" });
    let sort = sortKey || columns[0].key, dir = "asc";
    const draw = () => {
      table.innerHTML = "";
      const col = columns.find((c) => c.key === sort);
      const keyed = rows.map((r, i) => ({ r, i, v: col.get(r) }));
      keyed.sort((x, y) => {
        const xn = x.v === null || x.v === undefined, yn = y.v === null || y.v === undefined;
        if (xn && yn) return x.i - y.i; if (xn) return 1; if (yn) return -1;
        const c = compareValues(col.type, x.v, y.v);
        return c !== 0 ? c * (dir === "desc" ? -1 : 1) : x.i - y.i;
      });
      const tr = el("tr", { class: "cols" });
      for (const c of columns) {
        const th = el("th", { class: c.type === "num" ? "num" : "", text: c.label, title: "sort by " + c.label });
        if (c.key === sort) th.setAttribute("aria-sort", dir === "desc" ? "descending" : "ascending");
        th.addEventListener("click", () => { if (sort === c.key) dir = dir === "asc" ? "desc" : "asc"; else { sort = c.key; dir = "asc"; } draw(); });
        tr.append(th);
      }
      table.append(el("thead", null, tr));
      const maxes = {};
      for (const c of columns) if (c.bar) maxes[c.key] = Math.max(0, ...rows.map((r) => c.get(r)).filter((v) => typeof v === "number"));
      const tbody = el("tbody");
      for (const { r } of keyed) tbody.append(el("tr", null, columns.map((c) => {
        const v = c.get(r);
        const td = el("td", { class: (c.type === "num" ? "num" : "") + (c.bar ? " bar-cell" : "") + (c.wrap ? " reason" : ""), title: c.title ? c.title(r) : null });
        if (c.render) td.append(c.render(r, v));
        else if (v === null || v === undefined) td.append(el("span", { class: "na", text: "—" }));
        else if (c.type === "num") { td.append(document.createTextNode(fmt(v))); if (c.bar) td.append(el("span", { class: "bar-track" }, el("span", { class: "bar " + c.bar, style: "width:" + barWidth(v, maxes[c.key]).toFixed(2) + "%" }))); }
        else if (c.type === "level") td.append(levelCell(v));
        else td.textContent = v;
        return td;
      })));
      table.append(tbody);
    };
    draw();
    wrap.append(table);
    return wrap;
  }
  const sizeMini = (catKey) => {
    const S = (k, label) => ({ key: k, label, type: "num", bar: "sizes", get: (r) => (r.sizes && r.sizes[k] !== undefined) ? r.sizes[k] : null });
    if (catKey === "kem") return [S("pk", "pk"), S("sk", "sk"), S("ct", "ct")];
    if (catKey === "sig") return [S("pk", "pk"), S("sk", "sk"), S("sig_max", "sig")];
    return [S("pk_a", "pk A"), S("pk_b", "pk B"), S("msg_total", "msgs total"), { key: "passes", label: "passes", type: "num", get: (r) => (r.sizes && r.sizes.passes !== undefined) ? r.sizes.passes : null }];
  };
  function renderNotRun() {
    const panel = $("#panel-notrun");
    panel.innerHTML = "";
    const nb = DATA.not_benchmarked;
    const failed = nb.failed.map((id) => rowsById[id]);
    const qemu = nb.qemu_tier.map((id) => rowsById[id]);
    const unsup = nb.unsupported;
    panel.append(el("h2", { text: "Implementations without a complete board benchmark" }),
      el("p", { class: "section-intro", html: `From closest to furthest from a measurement: <b>${failed.length}</b> implementations were attempted on the board but did not complete every operation${(nb.pending || []).length ? `, <b>${nb.pending.length}</b> board-tier implementations are waiting for their first benchmark run` : ""}, <b>${qemu.length}</b> imported KEM/KEX implementations were classified as QEMU-only and never flashed, and <b>${unsup.length}</b> NGCC instances were never imported into ngccm4. Key sizes are shown wherever a KAT file or host result exists, so size comparisons stay possible.` }));

    // ---- group 1: board failures and partial runs
    panel.append(el("h2", { text: `1. Attempted on the board, incomplete (${failed.length})` }),
      el("p", { class: "section-intro", text: "Every crypto_sign implementation that links for the board was attempted regardless of its tier (one iteration, 10 minute cap per operation; 45 minutes for CEDRUSALPHA-160s). Partial rows keep the operations that did complete in the main tables. The reason text is the hand-written status from the benchmark report." }));
    const byKind = new Map();
    for (const r of failed) { const k = r.failure_kind || "other"; if (!byKind.has(k)) byKind.set(k, []); byKind.get(k).push(r); }
    const kindOrder = ["hardfault", "timeout", "link-overflow", "ram-qemu-evidence", "hangs", "too-slow", "partial", "other"];
    for (const k of kindOrder) {
      if (!byKind.has(k)) continue;
      const rows = byKind.get(k);
      const d = el("details", { class: "group", open: k === "hardfault" ? "" : null }, el("summary", null, [FAILURE_LABEL[k] || k, el("span", { class: "meta", text: `${rows.length} implementation${rows.length === 1 ? "" : "s"}` })]));
      d.append(miniTable([
        { key: "cat", label: "Category", type: "str", get: (r) => CATS[r.category] },
        { key: "scheme", label: "Scheme", type: "str", get: (r) => r.scheme, render: (r) => schemeCell(r) },
        { key: "impl", label: "Impl", type: "str", get: (r) => r.impl },
        { key: "level", label: "Level", type: "level", get: (r) => r.level },
        { key: "tier", label: "Tier", type: "str", get: (r) => r.tier },
        { key: "status", label: "Status", type: "status", get: (r) => r.run_status, render: (r, v) => badge(STATUS_CLASS[v], STATUS_LABEL[v]) },
        { key: "done", label: "Completed", type: "str", get: (r) => r.measured_ops.length ? r.measured_ops.join(", ") : (r.completed_ops.length ? r.completed_ops.join(", ") + " (not timed)" : "none") },
        { key: "code", label: "flash+ram", type: "num", get: (r) => r.code ? r.code.total : null, title: (r) => r.code ? "code size of the speed ELF (bytes)" : "did not link" },
        { key: "pk", label: "pk", type: "num", bar: "sizes", get: (r) => r.sizes ? (r.sizes.pk !== undefined ? r.sizes.pk : r.sizes.pk_b) : null },
        { key: "sk", label: "sk", type: "num", bar: "sizes", get: (r) => r.sizes ? (r.sizes.sk !== undefined ? r.sizes.sk : r.sizes.sk_b) : null },
        { key: "reason", label: "Reason", type: "str", wrap: true, get: (r) => r.status_text || "" },
      ], rows, "scheme"));
      panel.append(d);
    }

    // ---- group 1b: board-tier implementations without a benchmark run yet
    const pending = (nb.pending || []).map((id) => rowsById[id]);
    if (pending.length) {
      panel.append(el("h2", { text: `1b. Not benchmarked yet (${pending.length})` }),
        el("p", { class: "section-intro", text: "Board-tier implementations that were added after the last benchmark run (typically the submitters' Cortex-M4 ports imported from the NGCC packages). They build for the board and, where a KAT column is shown, pass the official test vectors on QEMU; cycle counts will appear after the next benchmark_schemes.py run." }));
      const d = el("details", { class: "group", open: "" }, el("summary", null, ["pending board run", el("span", { class: "meta", text: `${pending.length} implementation${pending.length === 1 ? "" : "s"}` })]));
      d.append(miniTable([
        { key: "cat", label: "Category", type: "str", get: (r) => CATS[r.category] },
        { key: "scheme", label: "Scheme", type: "str", get: (r) => r.scheme, render: (r) => schemeCell(r) },
        { key: "impl", label: "Impl", type: "str", get: (r) => r.impl },
        { key: "level", label: "Level", type: "level", get: (r) => r.level },
        { key: "kat", label: "KAT", type: "kat", get: (r) => r.kat.status, render: (r, v) => badge(KAT_CLASS[v] || "neutral", v, r.kat.detail) },
        { key: "code", label: "flash+ram", type: "num", get: (r) => r.code ? r.code.total : null, title: (r) => r.code ? "code size of the speed ELF (bytes)" : "not linked yet" },
        ...sizeMini(pending[0].category),
      ], pending, "scheme"));
      panel.append(d);
    }

    // ---- group 2: qemu tier
    panel.append(el("h2", { text: `2. Imported but QEMU-only, not attempted on the board (${qemu.length})` }),
      el("p", { class: "section-intro", text: "The importer classifies each instance by the memory it needs (ngcc_tier.txt). These KEM and key-exchange implementations need more than the board's 640 KB SRAM for static data, heap or stack, so they build and pass their KAT checks only on the QEMU mps2-an386 model with 16 MB PSRAM. Sizes below come from the QEMU testvectors run or the host build." }));
    const byScheme = new Map();
    for (const r of qemu) { const k = r.ngcc.title + " (" + CATS[r.category] + ")"; if (!byScheme.has(k)) byScheme.set(k, []); byScheme.get(k).push(r); }
    for (const [k, rows] of [...byScheme.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
      const d = el("details", { class: "group" }, el("summary", null, [k, " ", ngccLink(rows[0].ngcc), el("span", { class: "meta", text: `${rows.length} instance${rows.length === 1 ? "" : "s"}` })]));
      d.append(miniTable([
        { key: "scheme", label: "Scheme", type: "str", get: (r) => r.scheme },
        { key: "level", label: "Level", type: "level", get: (r) => r.level },
        { key: "kat", label: "KAT", type: "kat", get: (r) => r.kat.status, render: (r, v) => badge(KAT_CLASS[v] || "neutral", v, r.kat.detail) },
        ...sizeMini(rows[0].category),
      ], rows, "scheme"));
      panel.append(d);
    }

    // ---- group 3: never imported
    panel.append(el("h2", { text: `3. Not imported into ngccm4 (${unsup.length} instances)` }),
      el("p", { class: "section-intro", text: "The import manifest (tools/ngcc_manifest.json) marks these submissions, or individual parameter sets, as unsupported: they need GMP or x86 intrinsics, use unguarded 128-bit integers, do not compile as shipped, or have keys and tables of megabytes that no Cortex-M4 could hold. Sizes come from the submission's KAT file or its host-side results." }));
    const byReason = new Map();
    for (const e of unsup) { const k = e.reason_scope === "scheme" ? `${e.title}: ${e.reason}` : `${e.title} (selected instances): ${e.reason}`; if (!byReason.has(k)) byReason.set(k, []); byReason.get(k).push(e); }
    for (const [k, rows] of [...byReason.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
      const d = el("details", { class: "group" }, el("summary", null, [k, " ", ngccLink(rows[0].ngcc), el("span", { class: "meta", text: `${CATS[rows[0].category]} · ${rows.length} instance${rows.length === 1 ? "" : "s"}` })]));
      d.append(miniTable([
        { key: "instance", label: "Instance", type: "str", get: (r) => r.instance },
        { key: "level", label: "Level", type: "level", get: (r) => r.level },
        ...sizeMini(rows[0].category),
        { key: "src", label: "Size source", type: "str", get: (r) => r.sizes ? ({ kat: "KAT file", ngcc_results: "host results", kat_raw: "QEMU dump" }[r.sizes.source] || r.sizes.source) : "none" },
      ], rows, "instance"));
      panel.append(d);
    }
    if (DATA.meta.footnotes && DATA.meta.footnotes.length) panel.append(el("h3", { text: "Footnotes" }), el("ul", null, DATA.meta.footnotes.map((f) => el("li", { class: "note", text: f }))));
  }

  // ------------------------------------------------------------------ methodology panel
  function renderMethod() {
    const m = DATA.meta;
    const panel = $("#panel-method");
    panel.className = "panel method";
    const counts = m.counts;
    panel.innerHTML = `
      <h2>Platform and measurement</h2>
      <ul>${m.conditions.map((c) => `<li>${inlineCode(c)}</li>`).join("")}</ul>
      <p>Board: ${esc(m.board)}. Cycle counts are read from the DWT cycle counter around each API call. Code size is <code>arm-none-eabi-size</code> of the speed ELF and therefore includes the benchmark driver, the SM3/Keccak code and the HAL; compare schemes relative to each other, not as a library footprint. Stack usage comes from the stack app (canary painting) and was only collected for the KEM family.</p>
      <h2>What the tables show</h2>
      <ul>
        <li><b>Cycles</b>: choose average, median, minimum or maximum in the toolbar. The row details list all four plus the iteration count. "total" is the sum of the averages and is only shown when every operation completed.</li>
        <li><b>Sizes</b>: bytes of public key, secret key and ciphertext (KEM), signature (SIG, the largest over the ten KAT counts) or per-pass messages (KEX). The preferred source is the benchmarked binary itself (its testvectors output on QEMU), then a host build of the same reference code, then the submission's official KAT file. Where sources disagree the row details say so.</li>
        <li><b>Scheme</b>: click the name for details; the \u2197 next to it opens the submission's algorithm specification, a PDF copied from the NGCC package and served from this site (docs/specs/, tools/ngcc_specs.json). Addenda, the original submission zip and the public-comment thread are linked from the row details.</li>
        <li><b>Level</b>: the submitter's claimed classical security, normalised to one of 128, 192, 256, 384 or 512 bits. Where the instance name carries the number it is taken from the name; otherwise (parameter-set names such as <code>n=1024</code>, <code>L2</code>, <code>C1</code>, <code>I</code>, or the <code>160</code> hash-based sets) it is taken from the submission's specification. Hover a level to see the original parameter-set name and the exact claim. A dash means the submission states no level.</li>
        <li><b>Status</b>: <i>measured</i> (every operation timed), <i>partial</i> (some operations timed before a timeout or fault), <i>failed</i> (attempted on the board, nothing timed), <i>not yet run</i> (board-tier implementation added after the last benchmark run), <i>not run</i> (QEMU-tier KEM/KEX, never flashed). By default the tables show measured and partial rows; enable the other chips to include the rest, which still carry sizes and code size.</li>
        <li><b>KAT</b>: result of <code>kat_check.py</code> on QEMU (mps2-an386) against the official test vectors.</li>
        <li><b>Bars</b> are scaled to the largest visible value of each column, so filtering rescales them. Use the log scale when a few huge values flatten the rest.</li>
      </ul>
      <h2>KAT check notes</h2>
      <ul>${(m.kat_notes || []).map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
      <h2>Coverage</h2>
      <p>${counts.implementations} implementations (${counts.by_category.kem} KEM, ${counts.by_category.kex} KEX, ${counts.by_category.sig} SIG) from ${m.ngcc.schemes} NGCC Round-1 submissions with ${m.ngcc.instances} parameter sets (${counts.unsupported_instances} never imported). Submission packages were fetched from the NGCC candidate list${m.ngcc.fetched && m.ngcc.fetched.length ? ` between ${esc(m.ngcc.fetched[0])} and ${esc(m.ngcc.fetched[1])}` : ""}.</p>
      <h2>Reproducing</h2>
      <pre>git clone --recursive https://github.com/ngccm4dev/ngccm4.git
python3 benchmark_schemes.py PLATFORM=nucleo-l4r5zi --apps speed      # all board-tier schemes
python3 kat_check.py --md Out/kat_summary.md                           # KAT check on QEMU
python3 tools/make_site_data.py --ngcc-root NGCC                    # regenerate docs/data</pre>
      <p>Data files: <a href="data/benchmark.json" download>benchmark.json</a> (generated ${esc(m.generated_on)}${m.git_rev ? ` from commit <code>${esc(m.git_rev)}</code>` : ""}); sources ${Object.values(m.sources).map((s) => `<code>${esc(s)}</code>`).join(", ")}.</p>`;
  }

  // ------------------------------------------------------------------ header / footer / tabs
  function renderHeader() {
    const m = DATA.meta;
    const c = m.counts;
    $("#subtitle").innerHTML = inlineCode(`NGCC Round-1 post-quantum candidates measured on ${m.board}. ${m.conditions[0] || ""}`);
    const measured = (s) => Object.entries(c.by_status).filter(([k]) => k.endsWith("." + s)).reduce((a, [, v]) => a + v, 0);
    const tiles = [
      [c.implementations, "implementations"],
      [measured("measured"), "fully measured"],
      [measured("partial"), "partially measured"],
      [measured("failed") + measured("not-run") + measured("pending"), "no board result"],
      [c.unsupported_instances, "NGCC instances not imported"],
      [m.ngcc.schemes, "NGCC submissions"],
    ];
    $("#stat-row").replaceChildren(...tiles.map(([n, label]) => el("div", { class: "stat" }, [el("b", { text: fmt(n) }), el("span", { text: label })])));
    $("#footer").innerHTML = `ngccm4 benchmark site · data generated ${esc(m.generated_on)} by <code>${esc(m.generator)}</code>${m.git_rev ? ` at <code>${esc(m.git_rev)}</code>` : ""} · <a href="${esc(m.repo)}" rel="noopener">ngccm4dev/ngccm4</a>`;
  }
  function render() {
    for (const b of document.querySelectorAll("#tabs button")) b.setAttribute("aria-selected", b.dataset.tab === state.tab ? "true" : "false");
    $("#panel-table").hidden = !(state.tab in CATS);
    $("#panel-notrun").hidden = state.tab !== "notrun";
    $("#panel-method").hidden = state.tab !== "method";
    if (state.tab in CATS) { renderToolbar(); renderTable(); }
    writeHash();
  }

  // ------------------------------------------------------------------ theme
  function applyTheme(t) {
    if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
    else document.documentElement.removeAttribute("data-theme");
    $("#theme-toggle").textContent = "Theme: " + (t || "auto");
  }
  let theme = null;
  try { theme = localStorage.getItem("ngccm4-theme"); } catch (e) { /* ignore */ }
  applyTheme(theme);
  $("#theme-toggle").addEventListener("click", () => {
    theme = theme === null ? "dark" : theme === "dark" ? "light" : null;
    try { theme ? localStorage.setItem("ngccm4-theme", theme) : localStorage.removeItem("ngccm4-theme"); } catch (e) { /* ignore */ }
    applyTheme(theme);
  });

  // ------------------------------------------------------------------ wiring
  readHash();
  if (!(state.tab in CATS) && state.tab !== "notrun" && state.tab !== "method") state.tab = "kem";
  renderHeader();
  renderNotRun();
  renderMethod();
  for (const b of document.querySelectorAll("#tabs button")) b.addEventListener("click", () => { state.tab = b.dataset.tab; render(); });
  $("#search").addEventListener("input", (e) => { state.q = e.target.value; render(); });
  $("#stat-select").addEventListener("change", (e) => { state.stat = e.target.value; render(); });
  $("#bars-select").addEventListener("change", (e) => { state.bars = e.target.value; render(); });
  $("#csv-btn").addEventListener("click", downloadCsv);
  window.addEventListener("hashchange", () => { readHash(); render(); });
  render();
})();
