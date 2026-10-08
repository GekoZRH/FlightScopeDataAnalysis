"use strict";

const $ = (id) => document.getElementById(id);
const INTENTS = [12, 11, 10, 9];
const INTENT_COLORS = { full: "#378ADD", "11": "#1D9E75", "10": "#BA7517", "9": "#D4537E" };
let currentTab = "swing";

// ---------------------------------------------------------------- helpers

async function api(path, { params, body } = {}) {
  let url = path;
  if (params) url += "?" + new URLSearchParams(params);
  const options = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json", "X-Golf": "1" }, body: JSON.stringify(body),
  };
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({ error: "The server sent an unreadable answer." }));
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function showError(message) {
  const box = $("error");
  box.textContent = message;
  box.hidden = !message;
}

function guard(fn) {
  return async (...args) => {
    try { showError(""); return await fn(...args); } catch (error) { showError(error.message); console.error(error); }
  };
}

const num = (v, d = 1) => (v == null ? "–" : Number(v).toFixed(d));
const signed = (v, d = 1) => (v == null ? "–" : (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(d));
const dateLabel = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "2-digit" });
const intentName = (i) => (i === 12 ? "full" : String(i));

function change(c, unit, { colour = false, digits = 1 } = {}) {
  if (!c || c.est == null) return '<span class="pm">–</span>';
  const cls = colour ? (c.dir === -1 ? "good" : c.dir === 1 ? "bad" : "") : "";
  const half = (c.hi - c.lo) / 2;
  return `<span class="${cls}">${signed(c.est, digits)} ${unit}</span> <span class="pm">±${num(half, digits)}</span>`;
}

function verdict(dir) {
  if (dir === -1) return '<span class="pill good">tighter</span>';
  if (dir === 1) return '<span class="pill warn">broader</span>';
  if (dir === 0) return '<span class="pill">similar</span>';
  return '<span class="pill">too few shots</span>';
}

function fillSelect(select, values, labels) {
  const previous = select.value;
  select.innerHTML = values.map((v, i) => `<option value="${v}">${labels ? labels[i] : v}</option>`).join("");
  if (values.includes(previous)) select.value = previous;
}

function kpis(el, kpi) {
  el.innerHTML = [
    ["Shots", kpi.shots, ""], ["Clubs used", kpi.clubs, ""],
    ["Tighter", kpi.tighter, "good"], ["Broader", kpi.broader, "bad"],
  ].map(([name, value, cls]) => `<div class="kpi"><span>${name}</span><b class="${cls}">${value}</b></div>`).join("");
}

function css(name) { return getComputedStyle(document.body).getPropertyValue(name).trim(); }

function rgba(hex, alpha) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

function baseLayout(extra = {}) {
  const grid = css("--border");
  const axis = { gridcolor: grid, zerolinecolor: css("--border-strong"), linecolor: css("--border-strong"), automargin: true };
  return Object.assign({
    margin: { l: 56, r: 16, t: 10, b: 40 }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: css("--text"), size: 12 }, legend: { orientation: "h", y: 1.14 }, hovermode: "closest",
  }, extra, {
    xaxis: Object.assign({}, axis, extra.xaxis || {}),
    yaxis: Object.assign({}, axis, extra.yaxis || {}),
  });
}

function draw(id, traces, layout) {
  Plotly.react(id, traces, layout, { displaylogo: false, responsive: true, displayModeBar: false });
}

// One line per series over the sessions; evenly spaced, labelled with the session date.
function sessionChart(id, dates, series, { title, band = false, height }) {
  const traces = [];
  series.forEach((s) => {
    if (band && s.lo) {
      const keep = dates.map((_, i) => i).filter((i) => s.lo[i] != null && s.hi[i] != null);
      traces.push({
        x: keep.map((i) => dates[i]).concat(keep.map((i) => dates[i]).reverse()),
        y: keep.map((i) => s.hi[i]).concat(keep.map((i) => s.lo[i]).reverse()),
        fill: "toself", fillcolor: rgba(s.color, 0.16), line: { width: 0 }, hoverinfo: "skip", showlegend: false,
      });
    }
    traces.push({
      x: dates, y: s.y, name: s.name, mode: "lines+markers", connectgaps: true,
      line: { color: s.color, width: 2 }, marker: { size: 7, color: s.color },
      customdata: dates.map((_, i) => [s.n ? s.n[i] : null, s.lo ? s.lo[i] : null, s.hi ? s.hi[i] : null]),
      hovertemplate: "%{y:.1f}   n=%{customdata[0]}   95%: %{customdata[1]:.1f} to %{customdata[2]:.1f}<extra>" + s.name + "</extra>",
    });
  });
  if (height) $(id).style.height = height + "px";
  draw(id, traces, baseLayout({
    showlegend: series.length > 1,
    xaxis: { type: "category", tickvals: dates, ticktext: dates.map(dateLabel), showgrid: true },
    yaxis: { title: { text: title }, showgrid: true, gridcolor: css("--border-strong") },
  }));
}

// ---------------------------------------------------------------- data panel

async function renderDatasets(datasets) {
  const parts = [];
  const warnings = [];
  for (const [mode, label, tab] of [["swing", "Swing", "Bag"], ["pitching", "Pitching", "Wedge intents"]]) {
    const d = datasets[mode];
    $(mode === "swing" ? "swing-dir" : "pitching-dir").value = d.folder;
    if (!d.loaded) { parts.push(`${label}: not loaded (${d.error || "no data"})`); continue; }
    const used = d.sessions_selected === d.sessions ? `${d.sessions} sessions` : `${d.sessions_selected} of ${d.sessions} sessions selected`;
    parts.push(`${label}: ${d.files} files, ${d.shots.toLocaleString()} shots, ${used}, last ${dateLabel(d.last_session)}`);
    if (d.not_in_bag.length) {
      const list = d.not_in_bag.map((c) => `${c.club_variant} (${c.shots} shots)`).join(", ");
      warnings.push(`${label}: ${d.not_in_bag.length} club(s) recorded but not selected: ${list}. Choose them in the ${tab} tab.`);
    }
    if (d.unreadable.length) {
      warnings.push(`${label}: club labels that could not be read: ${d.unreadable.map((c) => c.raw_club).join(", ")}.`);
    }
  }
  $("data-status").textContent = parts.join("   |   ");
  $("warnings").innerHTML = warnings.map((w) => `<div class="warning">${w}</div>`).join("");
}

async function loadData() {
  const data = await api("/api/load", { body: { swing_dir: $("swing-dir").value.trim(), pitching_dir: $("pitching-dir").value.trim() } });
  await renderDatasets(data.datasets);
  await refreshAll();
}

async function browse(mode) {
  const { folder } = await api("/api/browse", { body: { mode } });
  if (folder) {
    $(mode === "swing" ? "swing-dir" : "pitching-dir").value = folder;
    await loadData();
  }
}

// ---------------------------------------------------------------- full swing

async function loadSwing() {
  const o = await api("/api/swing/overview");
  fillSelect($("sw-session"), o.sessions, o.sessions.map(dateLabel));
  fillSelect($("sw-disp-session"), o.sessions, o.sessions.map(dateLabel));
  fillSelect($("sw-club"), o.labels);
  fillSelect($("sw-disp-club"), o.labels);
  await Promise.all([swingReview(), swingProgress(), swingDispersion()]);
}

async function swingReview() {
  if (!$("sw-session").value) { $("sw-review").innerHTML = ""; kpis($("sw-kpis"), { shots: 0, clubs: 0, tighter: 0, broader: 0 }); return; }
  const r = await api("/api/swing/review", { params: { session: $("sw-session").value, baseline: $("sw-baseline").value } });
  kpis($("sw-kpis"), r.kpi);
  const rows = r.rows.map((row) => {
    const c = row.measures.carry, l = row.measures.lateral;
    return `<tr><td>${row.label}</td><td>${row.n}</td><td>${num(c.mean)} m</td><td>${change(c.d_mean, "m")}</td>` +
      `<td>${num(c.sd)} m</td><td>${change(c.d_sd, "m", { colour: true })}</td>` +
      `<td>${num(l.sd)} m</td><td>${change(l.d_sd, "m", { colour: true })}</td><td>${verdict(row.verdict)}</td></tr>`;
  }).join("");
  $("sw-review").innerHTML = "<tr><th>Club</th><th>Shots</th><th>Mean carry</th><th>Mean vs before</th>" +
    "<th>Carry spread (sd)</th><th>Spread vs before</th><th>Lateral spread (sd)</th><th>Spread vs before</th><th>Carry spread</th></tr>" +
    (rows || '<tr><td colspan="9" class="muted">No shots for the selected clubs in this session.</td></tr>');
}

async function swingProgress() {
  const label = $("sw-club").value;
  if (!label) return;
  const d = await api("/api/swing/progress", { params: { label } });
  const s = d.sessions, dates = s.map((x) => x.date), n = s.map((x) => x.n);
  sessionChart("sw-progress-1", dates, [{ name: "Mean carry", color: "#378ADD", y: s.map((x) => x.carry_mean), lo: s.map((x) => x.carry_mean_lo), hi: s.map((x) => x.carry_mean_hi), n }],
    { title: "Mean carry (m)", band: true });
  const metric = $("sw-metric").value;
  const spec = {
    carry_sd: ["Carry spread, sd (m)", "carry_sd", "carry_sd_lo", "carry_sd_hi"],
    lat_sd: ["Lateral spread, sd (m)", "lat_sd", "lat_sd_lo", "lat_sd_hi"],
    lat_mean: ["Lateral mean (m, negative = left)", "lat_mean", "lat_mean_lo", "lat_mean_hi"],
  }[metric];
  sessionChart("sw-progress-2", dates, [{ name: spec[0], color: "#1D9E75", y: s.map((x) => x[spec[1]]), lo: s.map((x) => x[spec[2]]), hi: s.map((x) => x[spec[3]]), n }],
    { title: spec[0], band: true });
}

function disperionTable(d) {
  const n = d.now_stats, b = d.before_stats;
  const row = (name, a, c, digits = 1) => `<tr><td>${name}</td><td>${num(a, digits)}</td><td>${num(c, digits)}</td></tr>`;
  return `<table><tr><th></th><th>This session (${n.n})</th><th>Before (${b.n})</th></tr>` +
    row("Carry sd (m)", n.carry_sd, b.carry_sd) + row("Lateral sd (m)", n.lat_sd, b.lat_sd) +
    row("Mean carry (m)", n.carry_mean, b.carry_mean) + row("Mean lateral (m)", n.lat_mean, b.lat_mean) + "</table>" +
    `<p style="margin-top:8px">Carry ${verdict(d.verdict.carry)} &nbsp; Lateral ${verdict(d.verdict.lateral)}</p>` +
    '<p class="muted small">Filled dots: this session. Grey dots: the earlier shots. Solid rings: middle 68% (and dotted 95%) now. Dashed rings: the same before. Faint rings: each earlier session.</p>';
}

async function swingDispersion() {
  const label = $("sw-disp-club").value, session = $("sw-disp-session").value;
  if (!label || !session) return;
  const d = await api("/api/swing/dispersion", { params: { label, session, compare: $("sw-disp-compare").value } });
  const line = (ring, color, dash, width, name, show = true) => ({
    x: ring.map((p) => p[0]), y: ring.map((p) => p[1]), mode: "lines", name, showlegend: show,
    line: { color, dash, width }, hoverinfo: "skip",
  });
  const grey = css("--muted"), accent = css("--accent");
  const traces = [];
  d.sessions.forEach((s, i) => traces.push(line(s.ring, rgba("#888780", 0.45), "solid", 1, "earlier sessions", i === 0)));
  traces.push({ x: d.before.lateral, y: d.before.carry, mode: "markers", name: "before", marker: { color: rgba("#888780", 0.5), size: 6 },
    hovertemplate: "lateral %{x} m, carry %{y} m<extra>before</extra>" });
  if (d.rings.before) {
    traces.push(line(d.rings.before["95"], grey, "dash", 1, "before 95%", false));
    traces.push(line(d.rings.before["68"], grey, "dash", 2, "before 68%"));
  }
  traces.push({ x: d.now.lateral, y: d.now.carry, mode: "markers", name: "this session", marker: { color: accent, size: 10 },
    hovertemplate: "lateral %{x} m, carry %{y} m<extra>this session</extra>" });
  if (d.rings.now) {
    traces.push(line(d.rings.now["95"], accent, "dot", 2, "now 95%", false));
    traces.push(line(d.rings.now["68"], accent, "solid", 2.5, "now 68%"));
  }
  draw("sw-disp", traces, baseLayout({
    xaxis: { title: { text: "Lateral (m, negative = left)" }, zeroline: true },
    yaxis: { title: { text: "Carry (m)" } },
  }));
  $("sw-disp-table").innerHTML = disperionTable(d);
}

// ---------------------------------------------------------------- pitching

async function loadPitching() {
  const o = await api("/api/pitching/overview");
  fillSelect($("pt-session"), o.sessions, o.sessions.map(dateLabel));
  fillSelect($("pt-club"), o.clubs);
  await Promise.all([pitchingReview(), pitchingAccuracy(), pitchingStraightness(), pitchingLadder()]);
}

function spreadCell(m, unit, digits = 1) {
  const c = m.d_sd;
  const delta = c && c.est != null ? ` <span class="${c.dir === -1 ? "good" : c.dir === 1 ? "bad" : "pm"}">(${signed(c.est, digits)})</span>` : "";
  return `${num(m.sd, digits)} ${unit}${delta}`;
}

async function pitchingReview() {
  if (!$("pt-session").value) { $("pt-review").innerHTML = ""; kpis($("pt-kpis"), { shots: 0, clubs: 0, tighter: 0, broader: 0 }); return; }
  const r = await api("/api/pitching/review", { params: { session: $("pt-session").value, baseline: $("pt-baseline").value } });
  kpis($("pt-kpis"), r.kpi);
  const rows = r.rows.map((row) => {
    const s = row.measures.speed, c = row.measures.carry, l = row.measures.lateral;
    return `<tr><td>${row.label}</td><td>${row.n}</td><td>${num(s.mean)} mph</td><td>${spreadCell(s, "mph")}</td>` +
      `<td>${num(c.mean, 0)} m</td><td>${spreadCell(c, "m")}</td><td>${spreadCell(l, "m")}</td><td>${verdict(row.verdict)}</td></tr>`;
  }).join("");
  $("pt-review").innerHTML = "<tr><th>Wedge, intent</th><th>Shots</th><th>Club speed</th><th>Speed spread (sd)</th>" +
    "<th>Carry (sim.)</th><th>Carry spread (sd)</th><th>Lateral spread (sd)</th><th>Speed spread</th></tr>" +
    (rows || '<tr><td colspan="8" class="muted">No shots for the selected wedges in this session.</td></tr>');
}

async function pitchingAccuracy() {
  const club = $("pt-club").value;
  if (!club) return;
  const d = await api("/api/pitching/accuracy", { params: { club, measure: $("pt-measure").value } });
  const series = d.series.map((s) => ({ name: s.name, color: INTENT_COLORS[s.name], y: s.y, lo: s.lo, hi: s.hi, n: s.n }));
  sessionChart("pt-accuracy", d.sessions, series, { title: d.title, height: 320 });
}

async function pitchingStraightness() {
  const d = await api("/api/pitching/straightness");
  const key = { sd: (r) => r.sd, offset: (r) => Math.abs(r.mean), rms: (r) => r.rms }[$("pt-sort").value];
  const rows = d.rows.filter((r) => r.n > 1).sort((a, b) => key(a) - key(b));
  const names = rows.map((r) => r.label + (r.short ? "*" : ""));
  const bars = (lo, hi) => ({ x: rows.flatMap((r) => [r[lo], r[hi], null]), y: names.flatMap((n) => [n, n, null]) });
  const accent = "#378ADD";
  const traces = [
    Object.assign(bars("lo95", "hi95"), { mode: "lines", line: { color: rgba(accent, 0.3), width: 14 }, hoverinfo: "skip", showlegend: false }),
    Object.assign(bars("lo68", "hi68"), { mode: "lines", line: { color: accent, width: 14 }, hoverinfo: "skip", showlegend: false }),
    { x: rows.map((r) => r.mean), y: names, mode: "markers", marker: { color: css("--surface"), size: 9, line: { color: accent, width: 2 } },
      customdata: rows.map((r) => [r.n, r.sd]), showlegend: false,
      hovertemplate: "mean %{x:.1f} m, sd %{customdata[1]:.1f} m (n=%{customdata[0]})<extra></extra>" },
  ];
  $("pt-straight").style.height = Math.max(240, 44 * rows.length + 70) + "px";
  draw("pt-straight", traces, baseLayout({
    margin: { l: 90, r: 16, t: 10, b: 44 },
    xaxis: { title: { text: "Lateral miss (m); negative = left of the target line" }, zeroline: true, zerolinewidth: 2 },
    yaxis: { type: "category", categoryorder: "array", categoryarray: names, autorange: "reversed", showgrid: true },
  }));
}

async function pitchingLadder() {
  const target = parseFloat($("pt-target").value), tol = parseFloat($("pt-tol").value);
  if (!(target > 0) || !(tol > 0)) return;
  const d = await api("/api/pitching/ladder", { params: { target, tolerance: tol } });
  const rows = d.rows.map((r, i) => `<tr><td>${r.label}${i === 0 ? ' <span class="pill good">best</span>' : ""}${r.short ? "*" : ""}</td>` +
    `<td>${r.n}</td><td>${num(r.mean, 0)} m</td><td>${num(r.sd)} m</td><td>${num(r.lat_sd)} m</td><td>${Math.round(r.chance * 100)}%</td></tr>`).join("");
  $("pt-ladder").innerHTML = `<tr><th>Option</th><th>Shots</th><th>Mean carry</th><th>Carry spread (sd)</th><th>Lateral spread (sd)</th><th>Chance within ±${tol} m</th></tr>` +
    (rows || '<tr><td colspan="6" class="muted">No wedge has enough shots.</td></tr>');
}

// ---------------------------------------------------------------- sessions

const sessionRows = { swing: [], pitching: [] };
const sessionWeeks = { window: 4, fallback: 12 };
const sessionTimer = {};

async function loadSessions() {
  for (const mode of ["swing", "pitching"]) {
    const d = await api("/api/sessions", { params: { mode } });
    sessionRows[mode] = d.sessions;
    if (d.loaded) { sessionWeeks.window = d.window_weeks; sessionWeeks.fallback = d.fallback_weeks; }
    renderSessions(mode);
  }
  for (const mode of ["swing", "pitching"]) {
    $(`ss-${mode}-w1`).textContent = `Last ${sessionWeeks.window} weeks`;
    $(`ss-${mode}-w2`).textContent = `Last ${sessionWeeks.fallback} weeks`;
  }
}

function renderSessions(mode) {
  const rows = sessionRows[mode];
  const chosen = rows.filter((r) => r.selected);
  const shots = chosen.reduce((sum, r) => sum + r.shots, 0);
  $(`ss-${mode}-summary`).textContent = rows.length
    ? `${chosen.length} of ${rows.length} sessions selected, ${shots.toLocaleString()} shots`
    : "No data loaded.";
  const body = rows.map((r) =>
    `<tr><td><input type="checkbox" data-mode="${mode}" data-date="${r.date}"${r.selected ? " checked" : ""}></td>` +
    `<td>${dateLabel(r.date)}</td><td>${r.shots}</td><td>${r.clubs}</td><td class="muted">${r.files.join(", ")}</td></tr>`).join("");
  $(`ss-${mode}-table`).innerHTML = "<tr><th></th><th>Session</th><th>Shots</th><th>Clubs and intents</th><th>File</th></tr>" + body;
}

function applySelection(mode, predicate) {
  sessionRows[mode].forEach((r) => (r.selected = predicate(r)));
  renderSessions(mode);
  saveSessions(mode);
}

function saveSessions(mode) {
  clearTimeout(sessionTimer[mode]);
  sessionTimer[mode] = setTimeout(guard(async () => {
    const selected = sessionRows[mode].filter((r) => r.selected).map((r) => r.date);
    if (!selected.length) { showError("Select at least one session."); return; }
    const d = await api("/api/sessions", { body: { mode, selected } });
    sessionRows[mode] = d.sessions;
    renderSessions(mode);
    const state = await api("/api/state");
    await renderDatasets(state.datasets);
  }), 300);
}

function sessionPreset(mode, preset) {
  const rows = sessionRows[mode];
  if (!rows.length) return;
  const latest = new Date(rows[0].date + "T12:00:00");
  const withinWeeks = (weeks) => (r) => (latest - new Date(r.date + "T12:00:00")) / 86400000 < weeks * 7;
  if (preset === "all") applySelection(mode, () => true);
  else if (preset === "weeks1") applySelection(mode, withinWeeks(sessionWeeks.window));
  else if (preset === "weeks2") applySelection(mode, withinWeeks(sessionWeeks.fallback));
  else if (preset === "lastn") {
    const n = Math.max(1, parseInt($(`ss-${mode}-n`).value, 10) || 1);
    const newest = new Set(rows.slice(0, n).map((r) => r.date));
    applySelection(mode, (r) => newest.has(r.date));
  }
}

// ---------------------------------------------------------------- bag and wedge selection

let bagClubs = [];
async function loadBag() {
  const d = await api("/api/bag");
  bagClubs = d.clubs;
  renderBag();
}

function renderBag() {
  $("bag-chips").innerHTML = bagClubs.map((c, i) =>
    `<button type="button" class="chip${c.selected ? " on" : ""}" data-i="${i}">${c.selected ? "✓ " : ""}${c.club}` +
    `<small>${c.shots} shots, last ${dateLabel(c.last_session)}</small></button>`).join("");
  const chosen = bagClubs.filter((c) => c.selected);
  $("bag-order").innerHTML = chosen.map((c) => `<li>${c.club}</li>`).join("") || '<li class="muted">No club selected</li>';
}

async function saveBag() {
  const clubs = bagClubs.filter((c) => c.selected).map((c) => c.club);
  const d = await api("/api/bag", { body: { clubs } });
  bagClubs = d.clubs;
  renderBag();
  $("bag-msg").textContent = `Saved ${clubs.length} clubs. The next swing card and the Full swing tab use this bag.`;
  const state = await api("/api/state");
  await renderDatasets(state.datasets);
}

let wedgeRows = [], wedgeSelected = new Set();
const key = (club, intent) => club + "|" + intent;

async function loadWedges() {
  const d = await api("/api/wedges");
  wedgeRows = d.rows;
  wedgeSelected = new Set(d.rows.flatMap((r) => r.selected.map((i) => key(r.club, i))));
  renderWedges();
}

function renderWedges() {
  const head = "<tr><th>Wedge</th>" + INTENTS.map((i) => `<th>${intentName(i)}</th>`).join("") + "</tr>";
  const body = wedgeRows.map((r, rowIndex) => {
    const cells = INTENTS.map((i) => {
      const n = r.counts[i] || 0;
      if (!n) return '<td><button type="button" class="chip off" disabled>–</button></td>';
      const on = wedgeSelected.has(key(r.club, i));
      return `<td><button type="button" class="chip${on ? " on" : ""}" data-club="${r.club}" data-intent="${i}">${on ? "✓ " : ""}${n} shots</button></td>`;
    }).join("");
    return `<tr><td><button type="button" class="chip row-toggle" data-row="${rowIndex}">${r.club}</button></td>${cells}</tr>`;
  }).join("");
  $("wedge-grid").innerHTML = head + body;
}

async function saveWedges() {
  const pairs = [...wedgeSelected].map((k) => { const [club, intent] = k.split("|"); return [club, Number(intent)]; });
  await api("/api/wedges", { body: { pairs } });
  $("wedge-msg").textContent = `Saved ${pairs.length} wedge and intent combinations. The next wedge card and the Pitching tab use them.`;
  const state = await api("/api/state");
  await renderDatasets(state.datasets);
}

// ---------------------------------------------------------------- cards

async function makeCard(mode, prefix) {
  const button = $(prefix + "-card");
  button.disabled = true;
  $(prefix + "-card-msg").textContent = "Drawing the card…";
  try {
    const r = await api("/api/card", { body: { mode } });
    const flagged = r.flagged.length ? ` Fewer than 12 shots (*): ${r.flagged.map((f) => `${f.label} (${f.n})`).join(", ")}.` : "";
    const span = r.from === r.as_of ? dateLabel(r.as_of) : `${dateLabel(r.from)} to ${dateLabel(r.as_of)}`;
    $(prefix + "-card-msg").textContent = `Saved ${r.file} (${r.sessions} session${r.sessions === 1 ? "" : "s"}, ${span}, ${r.rows} rows). A dated copy is in the archive folder.${flagged}`;
    const image = $(prefix + "-card-img");
    image.src = r.url + "?t=" + Date.now();
    image.hidden = false;
  } finally {
    button.disabled = false;
  }
}

// ---------------------------------------------------------------- tabs and start

const refreshers = { sessions: loadSessions, swing: loadSwing, pitching: loadPitching, bag: loadBag, wedges: loadWedges };

async function showTab(name) {
  currentTab = name;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.dataset.tab === name));
  for (const id of Object.keys(refreshers)) $("tab-" + id).hidden = id !== name;
  await refreshers[name]();
}

async function refreshAll() { await refreshers[currentTab](); }

function wire() {
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", guard(() => showTab(t.dataset.tab))));
  $("load").addEventListener("click", guard(loadData));
  $("browse-swing").addEventListener("click", guard(() => browse("swing")));
  $("browse-pitching").addEventListener("click", guard(() => browse("pitching")));

  for (const id of ["sw-session", "sw-baseline"]) $(id).addEventListener("change", guard(swingReview));
  for (const id of ["sw-club", "sw-metric"]) $(id).addEventListener("change", guard(swingProgress));
  for (const id of ["sw-disp-club", "sw-disp-session", "sw-disp-compare"]) $(id).addEventListener("change", guard(swingDispersion));
  $("sw-card").addEventListener("click", guard(() => makeCard("swing", "sw")));

  for (const id of ["pt-session", "pt-baseline"]) $(id).addEventListener("change", guard(pitchingReview));
  for (const id of ["pt-club", "pt-measure"]) $(id).addEventListener("change", guard(pitchingAccuracy));
  $("pt-sort").addEventListener("change", guard(pitchingStraightness));
  let timer;
  for (const id of ["pt-target", "pt-tol"]) $(id).addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(guard(pitchingLadder), 300); });
  $("pt-card").addEventListener("click", guard(() => makeCard("pitching", "pt")));

  $("bag-chips").addEventListener("click", (event) => {
    const chip = event.target.closest(".chip");
    if (!chip) return;
    bagClubs[Number(chip.dataset.i)].selected = !bagClubs[Number(chip.dataset.i)].selected;
    $("bag-msg").textContent = "";
    renderBag();
  });
  $("bag-save").addEventListener("click", guard(saveBag));

  document.querySelectorAll("#tab-sessions .controls button[data-preset]").forEach((button) => {
    button.addEventListener("click", () => sessionPreset(button.closest(".controls").dataset.mode, button.dataset.preset));
  });
  $("tab-sessions").addEventListener("change", (event) => {
    const box = event.target;
    if (box.type !== "checkbox") return;
    const row = sessionRows[box.dataset.mode].find((r) => r.date === box.dataset.date);
    row.selected = box.checked;
    renderSessions(box.dataset.mode);
    saveSessions(box.dataset.mode);
  });

  $("wedge-grid").addEventListener("click", (event) => {
    const chip = event.target.closest(".chip");
    if (!chip || chip.disabled) return;
    if (chip.dataset.row !== undefined) {
      const row = wedgeRows[Number(chip.dataset.row)];
      const available = INTENTS.filter((i) => row.counts[i]);
      const allOn = available.every((i) => wedgeSelected.has(key(row.club, i)));
      available.forEach((i) => (allOn ? wedgeSelected.delete(key(row.club, i)) : wedgeSelected.add(key(row.club, i))));
    } else {
      const k = key(chip.dataset.club, chip.dataset.intent);
      wedgeSelected.has(k) ? wedgeSelected.delete(k) : wedgeSelected.add(k);
    }
    $("wedge-msg").textContent = "";
    renderWedges();
  });
  $("wedge-save").addEventListener("click", guard(saveWedges));
}

guard(async () => {
  wire();
  const state = await api("/api/state");
  await renderDatasets(state.datasets);
  await showTab("swing");
})();
