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
  const all = [["Shots", kpi.shots, ""], ["Clubs used", kpi.clubs, ""], ["Tighter", kpi.tighter, "good"], ["Broader", kpi.broader, "bad"]];
  el.innerHTML = all.filter(([, value]) => value !== undefined)
    .map(([name, value, cls]) => `<div class="kpi"><span>${name}</span><b class="${cls}">${value}</b></div>`).join("");
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
        mode: "lines", fill: "toself", fillcolor: rgba(s.color, 0.16), line: { width: 0 }, hoverinfo: "skip", showlegend: false,
      });
    }
    traces.push({
      x: dates, y: s.y, name: s.name, mode: "lines+markers", connectgaps: true,
      line: { color: s.color, width: 2, dash: s.dash || "solid" }, marker: { size: s.size || 7, color: s.color, symbol: s.symbol || "circle" },
      legendgroup: s.group, showlegend: s.legend !== false,
      customdata: dates.map((_, i) => [s.n ? s.n[i] : null, s.lo ? s.lo[i] : null, s.hi ? s.hi[i] : null]),
      hovertemplate: (s.hover || "%{y:.1f}   n=%{customdata[0]}   95%: %{customdata[1]:.1f} to %{customdata[2]:.1f}") + "<extra>" + s.name + "</extra>",
    });
  });
  if (height) $(id).style.height = height + "px";
  draw(id, traces, baseLayout({
    showlegend: series.length > 1,
    // the order must be given: Plotly otherwise orders categories by first appearance, and the band skips sessions without data
    xaxis: { type: "category", categoryorder: "array", categoryarray: dates, tickvals: dates, ticktext: dates.map(dateLabel), showgrid: true },
    yaxis: { title: { text: title }, showgrid: true, gridcolor: css("--border-strong") },
  }));
}

// ---------------------------------------------------------------- data panel

const KINDS = [["swing", "Swing", "Bag"], ["pitching", "Pitching", "Wedge intents"], ["stack", "Stack", ""]];

async function renderDatasets(datasets) {
  const parts = [];
  const warnings = [];
  for (const [mode, label, tab] of KINDS) {
    const d = datasets[mode];
    $(mode + "-dir").value = d.folder;
    if (!d.enabled) { parts.push(`${label}: no folder chosen`); continue; }
    if (!d.loaded) { parts.push(`${label}: not loaded (${d.error || "no data"})`); continue; }
    const used = d.sessions_selected === d.sessions ? `${d.sessions} sessions` : `${d.sessions_selected} of ${d.sessions} sessions selected`;
    parts.push(`${label}: ${d.files} files, ${d.shots.toLocaleString()} shots, ${used}, last ${dateLabel(d.last_session)}`);
    if (d.not_in_bag.length) {
      const list = d.not_in_bag.map((c) => `${c.club_variant} (${c.shots} shots)`).join(", ");
      warnings.push(`${label}: ${d.not_in_bag.length} club(s) recorded but not selected: ${list}. Choose them in the ${tab} tab.`);
    }
    if (d.unreadable.length) {
      const what = mode === "stack" ? "weights that could not be read" : "club labels that could not be read";
      warnings.push(`${label}: ${what}: ${d.unreadable.map((c) => c.raw_club).join(", ")}.`);
    }
  }
  const g = datasets.garmin;
  $("garmin-dir").value = g.folder;
  if (!g.enabled) parts.push("Garmin: no folder chosen");
  else if (!g.loaded) parts.push(`Garmin: not loaded (${g.error || "no data"})`);
  else parts.push(`Garmin: ${g.nights} nights, ${g.strength} strength and ${g.cardio} cardio sessions, up to ${dateLabel(g.last)}`);
  const cp = datasets.competition;
  $("competition-dir").value = cp.folder;
  if (!cp.enabled) parts.push("Competition: no folder chosen");
  else if (!cp.loaded) parts.push(`Competition: not loaded (${cp.error || "no rounds"})`);
  else parts.push(`Competition: ${cp.rounds} rounds, ${dateLabel(cp.first)} to ${dateLabel(cp.last)}`);
  if (cp.enabled && cp.error && cp.loaded) warnings.push(`Competition: the certificate could not be read (${cp.error}); the record made so far is used.`);
  for (const note of (cp.notes || [])) warnings.push(`Competition: ${note}`);
  const gf = datasets.golf;
  if (gf && gf.loaded) parts.push(`Garmin rounds: ${gf.rounds} full rounds, ${dateLabel(gf.first)} to ${dateLabel(gf.last)}`);
  const w = datasets.withings;
  $("withings-dir").value = w.folder;
  if (!w.enabled) parts.push("Withings: no folder chosen");
  else if (!w.loaded) parts.push(`Withings: not loaded (${w.error || "no data"})`);
  else parts.push(`Withings: ${w.weighings} weighings, ${dateLabel(w.first)} to ${dateLabel(w.last)}`);
  $("data-status").textContent = parts.join("   |   ");
  $("warnings").innerHTML = warnings.map((w) => `<div class="warning">${w}</div>`).join("");
  applyAvailability(datasets);
}

// Only the kinds of data that were loaded get tabs. A folder left empty means: not used.
let available = {};

function applyAvailability(datasets) {
  const loaded = (mode) => Boolean(datasets[mode] && datasets[mode].loaded);
  const any = loaded("swing") || loaded("pitching") || loaded("stack");
  const rounds = loaded("competition") || Boolean(datasets.golf && datasets.golf.loaded);
  const anyData = any || loaded("garmin") || loaded("withings") || rounds;  // health data and rounds alone have their own tabs
  available = {
    sessions: any, swing: loaded("swing"), bag: loaded("swing"),
    pitching: loaded("pitching"), wedges: loaded("pitching"), stack: loaded("stack"),
    garmin: loaded("garmin") || loaded("withings"),
    rounds,
  };
  document.querySelectorAll(".tab").forEach((tab) => (tab.hidden = !available[tab.dataset.tab]));
  $("tabs").hidden = !anyData;
  $("no-data").hidden = anyData;
  for (const id of Object.keys(available)) if (!available[id]) $("tab-" + id).hidden = true;
}

function firstAvailableTab() {
  return ["swing", "pitching", "stack", "sessions", "rounds", "garmin"].find((name) => available[name]);
}

async function loadData() {
  const body = {
    swing_dir: $("swing-dir").value.trim(), pitching_dir: $("pitching-dir").value.trim(), stack_dir: $("stack-dir").value.trim(),
    garmin_dir: $("garmin-dir").value.trim(), withings_dir: $("withings-dir").value.trim(),
    competition_dir: $("competition-dir").value.trim(),
  };
  const data = await api("/api/load", { body });
  await renderDatasets(data.datasets);
  const next = available[currentTab] ? currentTab : firstAvailableTab();
  if (next) await showTab(next);
}

async function browse(mode) {
  const { folder } = await api("/api/browse", { body: { mode } });
  if (folder) {
    $(mode + "-dir").value = folder;
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
  fillSelect($("lv-club"), o.labels);
  fillMeasureMenu($("sw-metric"), o.measures);
  await Promise.all([swingReview(), swingProgress(), swingDispersion(), swingLevers(), swingLeverBag()]);
}

function fillMeasureMenu(select, measures, fallback) {
  const previous = select.value || fallback;
  const groups = [...new Set(measures.map((m) => m.group))];
  select.innerHTML = groups.map((g) =>
    `<optgroup label="${g}">` + measures.filter((m) => m.group === g).map((m) => `<option value="${m.key}">${m.title}</option>`).join("") + "</optgroup>").join("");
  if (measures.some((m) => m.key === previous)) select.value = previous;
}

async function swingReview() {
  if (!$("sw-session").value) { $("sw-review").innerHTML = ""; kpis($("sw-kpis"), { shots: 0, clubs: 0 }); return; }
  const r = await api("/api/swing/review", { params: { session: $("sw-session").value, baseline: $("sw-baseline").value } });
  kpis($("sw-kpis"), { shots: r.kpi.shots, clubs: r.kpi.clubs });
  const history = (m, unit) => m.before.n ? `${num(m.before.mean)} ${unit}` : "–";
  const rows = r.rows.map((row) => {
    const c = row.measures.carry, l = row.measures.lateral;
    return `<tr><td>${row.label}</td><td>${row.n}</td>` +
      `<td>${num(c.mean)} m</td><td>${num(c.sd)} m</td>` +
      `<td>${history(c, "m")} <span class="pm">n=${c.before.n}</span></td><td>${c.before.n > 1 ? num(c.before.sd) + " m" : "–"}</td>` +
      `<td>${num(l.sd)} m</td><td>${l.before.n > 1 ? num(l.before.sd) + " m" : "–"}</td></tr>`;
  }).join("");
  $("sw-review").innerHTML = "<tr><th>Club</th><th>Shots</th><th>Session mean carry</th><th>Session carry spread (sd)</th>" +
    "<th>Historic carry</th><th>Historic carry spread (sd)</th><th>Session lateral spread (sd)</th><th>Historic lateral spread (sd)</th></tr>" +
    (rows || '<tr><td colspan="8" class="muted">No shots for the selected clubs in this session.</td></tr>');
}

// One measure per session for one club, for the swing or the pitching tab.
async function progressChart(path, label, measure, id, color) {
  const d = await api(path, { params: { label, measure } });
  if (!d.sessions.length) {
    draw(id, [], baseLayout({ annotations: [{ text: "No data for this selection", showarrow: false, font: { color: css("--muted") } }], xaxis: { visible: false }, yaxis: { visible: false } }));
    return;
  }
  // every selected session is on the axis; sessions without this club have no point and the line bridges them
  const byDate = new Map(d.sessions.map((x) => [x.date, x]));
  const pick = (field) => d.dates.map((date) => (byDate.has(date) ? byDate.get(date)[field] : null));
  sessionChart(id, d.dates, [{
    name: d.title, color, y: pick("y"), lo: pick("lo"), hi: pick("hi"), n: pick("n"),
  }], { title: d.title, band: true });
}

async function swingProgress() {
  const label = $("sw-club").value;
  if (!label) return;
  await Promise.all([
    progressChart("/api/swing/series", label, "carry_mean", "sw-progress-1", "#378ADD"),
    progressChart("/api/swing/series", label, "club_speed", "sw-progress-2", "#D4537E"),
    progressChart("/api/swing/series", label, $("sw-metric").value, "sw-progress-3", "#1D9E75"),
  ]);
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
  pitchingChoices = o.choices;
  fillSelect($("pt-club"), o.choices.map((c) => c.club));
  fillIntents();
  fillMeasureMenu($("pt-metric"), o.measures);
  fillSelect($("sc-club"), o.choices.map((c) => c.club));
  fillMeasureMenu($("sc-x"), o.shot_measures, "club_speed");
  fillMeasureMenu($("sc-y"), o.shot_measures, "carry");
  await Promise.all([pitchingReview(), pitchingProgress(), pitchingScatter(), pitchingStraightness(), pitchingLadder()]);
}

async function pitchingReview() {
  if (!$("pt-session").value) { $("pt-review").innerHTML = ""; kpis($("pt-kpis"), { shots: 0, clubs: 0 }); return; }
  const r = await api("/api/pitching/review", { params: { session: $("pt-session").value, baseline: $("pt-baseline").value } });
  kpis($("pt-kpis"), { shots: r.kpi.shots, clubs: r.kpi.clubs });
  const sd = (m, unit) => (m.n > 1 ? `${num(m.sd)} ${unit}` : "–");
  const historicSd = (m, unit) => (m.before.n > 1 ? `${num(m.before.sd)} ${unit}` : "–");
  const rows = r.rows.map((row) => {
    const s = row.measures.speed, c = row.measures.carry, l = row.measures.lateral;
    return `<tr><td>${row.club}</td><td>${intentName(row.intent)}</td><td>${row.n}</td>` +
      `<td>${num(s.mean)} mph</td><td>${sd(s, "mph")}</td>` +
      `<td>${s.before.n ? num(s.before.mean) + " mph" : "–"} <span class="pm">n=${s.before.n}</span></td><td>${historicSd(s, "mph")}</td>` +
      `<td>${num(c.mean, 0)} m</td><td>${sd(c, "m")}</td>` +
      `<td>${sd(l, "m")}</td><td>${historicSd(l, "m")}</td></tr>`;
  }).join("");
  $("pt-review").innerHTML = "<tr><th>Wedge</th><th>Intent</th><th>Shots</th><th>Session club speed</th><th>Session speed spread (sd)</th>" +
    "<th>Historic club speed</th><th>Historic speed spread (sd)</th><th>Session carry (sim.)</th><th>Session carry spread (sd)</th>" +
    "<th>Session lateral spread (sd)</th><th>Historic lateral spread (sd)</th></tr>" +
    (rows || '<tr><td colspan="11" class="muted">No shots for the selected wedges in this session.</td></tr>');
}

let pitchingChoices = [];

function fillIntents() {
  const choice = pitchingChoices.find((c) => c.club === $("pt-club").value);
  const intents = choice ? choice.intents : [];
  fillSelect($("pt-intent"), intents.map(String), intents.map(intentName));
}

async function pitchingProgress() {
  const club = $("pt-club").value, intent = Number($("pt-intent").value);
  if (!club || !intent) return;
  const label = intent === 12 ? club : `${club}_${intent}`;
  await Promise.all([
    progressChart("/api/pitching/series", label, "carry_mean", "pt-progress-1", "#378ADD"),
    progressChart("/api/pitching/series", label, "club_speed", "pt-progress-2", "#D4537E"),
    progressChart("/api/pitching/series", label, $("pt-metric").value, "pt-progress-3", "#1D9E75"),
  ]);
}

async function pitchingScatter() {
  const club = $("sc-club").value;
  if (!club) return;
  const d = await api("/api/pitching/scatter", { params: { club, x: $("sc-x").value, y: $("sc-y").value } });
  const traces = d.groups.map((g) => ({
    x: g.x, y: g.y, name: g.name, mode: "markers", marker: { color: INTENT_COLORS[g.name], size: 8, opacity: 0.8 },
    customdata: g.dates,
    hovertemplate: `${d.x.title}: %{x}<br>${d.y.title}: %{y}<br>%{customdata}<extra>${g.name}</extra>`,
  }));
  const fit = d.fit;
  if ($("sc-fit").checked && fit) {
    const all = d.groups.flatMap((g) => g.x);
    const lo = Math.min(...all), hi = Math.max(...all);
    traces.push({
      x: [lo, hi], y: [fit.slope * lo + fit.intercept, fit.slope * hi + fit.intercept], mode: "lines", name: "fit",
      line: { color: css("--muted"), dash: "dash", width: 2 }, hoverinfo: "skip",
    });
  }
  const shots = d.groups.reduce((sum, g) => sum + g.x.length, 0);
  $("sc-note").textContent = !shots ? "No shots with both measures for this wedge in the selected sessions."
    : `${shots} shots, colour = intent.` + (fit ? ` Correlation r = ${fit.r.toFixed(2)}; fitted slope ${Number(fit.slope.toPrecision(2))} (change in y per unit of x).` : "");
  draw("sc-plot", traces, baseLayout({
    xaxis: { title: { text: d.x.title }, showgrid: true }, yaxis: { title: { text: d.y.title }, showgrid: true },
  }));
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

const sessionRows = { swing: [], pitching: [], stack: [] };
const sessionWeeks = { window: 4, fallback: 12 };
const sessionTimer = {};

async function loadSessions() {
  for (const mode of ["swing", "pitching", "stack"]) {
    const d = await api("/api/sessions", { params: { mode } });
    sessionRows[mode] = d.sessions;
    if (d.loaded) { sessionWeeks.window = d.window_weeks; sessionWeeks.fallback = d.fallback_weeks; }
    $("ss-card-" + mode).hidden = !d.loaded;
    renderSessions(mode);
  }
  for (const mode of ["swing", "pitching", "stack"]) {
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
  $(`ss-${mode}-table`).innerHTML = `<tr><th></th><th>Session</th><th>Shots</th><th>${mode === "stack" ? "Weights" : "Clubs and intents"}</th><th>File</th></tr>` + body;
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

// ---------------------------------------------------------------- distance levers

const LEVER_DECIMALS = { smash: 3, club_speed_mph: 1, launch_v_deg: 1, spin_rpm: 0, aoa_deg: 1, dynamic_loft_deg: 1, club_path_deg: 1, ftp_deg: 1 };
const leverNumber = (key, value) => (value == null ? "–" : Number(value).toFixed(LEVER_DECIMALS[key] ?? 1));
const leverName = (f) => f.title.split(" (")[0];
const leverUnit = (f) => (f.unit ? ` ${f.unit}` : "");

function leverDirection(f) {
  return !f.lever ? "for comparison" : f.clear ? (f.effect > 0 ? "more is better" : "less is better") : "no clear effect";
}

function drawLeverGroup(g) {
  const id = `lv-${g.key}`;
  $(`${id}-title`).textContent = g.title;
  if (!g.ok) {
    $(`${id}-verdict`).textContent = g.reason;
    $(`${id}-note`).textContent = "";
    $(`${id}-plot`).style.height = "60px";
    draw(`${id}-plot`, [], baseLayout({ xaxis: { visible: false }, yaxis: { visible: false } }));
    return;
  }
  $(`${id}-verdict`).textContent = g.verdict;
  const names = g.factors.map((f) => `${leverName(f)}: avg ${leverNumber(f.key, f.mean)}${leverUnit(f)}, 1 SD = ${leverNumber(f.key, f.sd)}${leverUnit(f)}`);
  const accent = css("--accent"), muted = css("--muted");
  const colors = g.factors.map((f) => (!f.lever ? muted : f.clear ? accent : rgba("#378ADD", 0.45)));
  const widest = Math.max(...g.factors.map((f) => Math.max(Math.abs(f.low), Math.abs(f.high))));
  const traces = [
    { x: g.factors.flatMap((f) => [f.low, f.high, null]), y: g.factors.flatMap((_, i) => [names[i], names[i], null]), mode: "lines",
      line: { color: rgba("#378ADD", 0.45), width: 9 }, hoverinfo: "skip", showlegend: false },
    { x: g.factors.map((f) => f.effect), y: names, mode: "markers", showlegend: false, marker: { size: 10, color: colors },
      customdata: g.factors.map((f) => [f.low, f.high]),
      hovertemplate: "%{x:+.1f} m for 1 SD more  (%{customdata[0]:+.1f} to %{customdata[1]:+.1f})<extra></extra>" },
    { x: g.factors.map((f) => Math.max(f.high, 0) + widest * 0.06), y: names, mode: "text", showlegend: false, hoverinfo: "skip",
      text: g.factors.map(leverDirection), textposition: "middle right", textfont: { size: 11, color: muted } },
  ];
  $(`${id}-plot`).style.height = Math.max(190, 44 * g.factors.length + 70) + "px";
  draw(`${id}-plot`, traces, baseLayout({
    margin: { l: 330, r: 20, t: 8, b: 44 },
    xaxis: { title: { text: "Carry change (m) for 1 SD more of the factor" }, zeroline: true, zerolinewidth: 2, showgrid: true, range: [-widest * 1.15, widest * 1.9] },
    yaxis: { type: "category", categoryorder: "array", categoryarray: names, autorange: "reversed", showgrid: true },
  }));
  $(`${id}-note`).textContent = `${g.n} shots in ${g.sessions} sessions, average carry ${num(g.carry_mean)} m (sd ${num(g.carry_sd)} m). These factors together explain ${Math.round(100 * g.r2)}% of the differences in carry.`;
}

async function swingLevers() {
  if (!$("lv-club").value) return;
  const d = await api("/api/swing/levers", { params: { label: $("lv-club").value } });
  d.groups.forEach(drawLeverGroup);
}

function leverCell(f) {
  if (!f) return "<td>–</td>";
  const strength = Math.min(Math.abs(f.effect) / 6, 1) * 0.55;
  const color = f.effect >= 0 ? `rgba(55,138,221,${strength})` : `rgba(232,144,58,${strength})`;
  const text = `${signed(f.effect, 1)}`;
  const title = `${signed(f.effect, 1)} m (${signed(f.low, 1)} to ${signed(f.high, 1)}) for 1 SD = ${leverNumber(f.key, f.sd)}${leverUnit(f)}`;
  return `<td style="background:${color}" title="${title}">${f.clear ? `<b>${text}</b>` : `<span style="opacity:.75">${text}</span>`}</td>`;
}

async function swingLeverBag() {
  const d = await api("/api/swing/levers-bag");
  for (const group of d.groups) {
    const head = group.factors.map((f) => `<th title="${f.title}">${leverName(f)}</th>`).join("");
    const body = d.rows.map((r) => {
      const g = r.groups[group.key];
      if (!g.ok) return `<tr><td style="text-align:left">${r.label}</td><td class="muted" colspan="${group.factors.length + 2}">not enough shots or sessions with all of these factors</td></tr>`;
      const cells = group.factors.map((f) => leverCell(g.factors.find((x) => x.key === f.key))).join("");
      const biggest = g.biggest ? leverName(g.factors.find((x) => x.key === g.biggest)) : "none clear";
      return `<tr><td style="text-align:left">${r.label}</td><td>${g.n}</td>${cells}<td style="text-align:left">${biggest}</td></tr>`;
    }).join("");
    $(`lvb-${group.key}-table`).innerHTML = `<tr><th style="text-align:left">Club</th><th>Shots</th>${head}<th style="text-align:left">Largest lever</th></tr>` + body;
  }
}

// ---------------------------------------------------------------- stack

// One marker shape per weight, so lines can be told apart without relying on colour alone.
// Weights are numbered from the heaviest, so neighbouring weights never share a shape (12 shapes, then they repeat).
const MARKER_SYMBOLS = [
  "circle", "square", "diamond", "triangle-up", "triangle-down", "pentagon",
  "hexagon", "star", "cross", "x", "triangle-left", "triangle-right",
];

// Heavy weights red, light weights blue.
function weightColor(weight, lightest, heaviest) {
  const t = heaviest > lightest ? (weight - lightest) / (heaviest - lightest) : 0.5;
  return `hsl(${Math.round(210 - 210 * t)}, 70%, 52%)`;
}

async function loadStack() {
  const d = await api("/api/stack/progress");
  if (!d.series.length) {
    draw("stack-progress", [], baseLayout({ annotations: [{ text: "No stack swings in the selected sessions", showarrow: false, font: { color: css("--muted") } }], xaxis: { visible: false }, yaxis: { visible: false } }));
    return;
  }
  const weights = d.series.map((s) => s.weight);
  const lightest = Math.min(...weights), heaviest = Math.max(...weights);
  // per weight: the average as a solid line with filled markers, the fastest swing as a dashed line with open markers of the same shape
  const series = [];
  d.series.forEach((s, i) => {
    const color = weightColor(s.weight, lightest, heaviest), symbol = MARKER_SYMBOLS[i % MARKER_SYMBOLS.length];
    if ($("st-avg").checked) {
      series.push({ name: s.name, group: s.name, color, y: s.y, lo: s.lo, hi: s.hi, n: s.n, symbol, size: 10 });
    }
    if ($("st-max").checked) {
      series.push({ name: `${s.name} max`, group: s.name, legend: !$("st-avg").checked, color, y: s.max, n: s.n, symbol: symbol + "-open", size: 10, dash: "dash",
        hover: "fastest swing %{y:.1f}   of n=%{customdata[0]}" });
    }
  });
  sessionChart("stack-progress", d.dates, series, { title: "Club head speed (mph)", band: false, height: 460 });
}

// ---------------------------------------------------------------- rounds

function periodChoices(days, years) {
  return [["all", "All data"], ...days.map((n) => [`days:${n}`, n === 90 ? "Last 3 months" : n === 365 ? "Last 12 months" : `Last ${n} days`]),
    ...years.map((y) => [`year:${y}`, String(y)])];
}

async function loadRounds() {
  const o = await api("/api/rounds/overview");
  const c = o.competition, g = o.garmin;
  for (const id of ["rc-card"]) $(id).hidden = !c.loaded;
  for (const id of ["rg-card", "rs-card", "rl-card"]) $(id).hidden = !g.loaded;
  fillSelect($("rc-measure"), c.measures.map((m) => m.key), c.measures.map((m) => m.title));
  fillSelect($("rg-measure"), g.measures.map((m) => m.key), g.measures.map((m) => m.title));
  const cp = periodChoices(o.days, c.years), gp = periodChoices(o.days, g.years);
  fillSelect($("rc-period"), cp.map((p) => p[0]), cp.map((p) => p[1]));
  fillSelect($("rg-period"), gp.map((p) => p[0]), gp.map((p) => p[1]));
  await Promise.all([c.loaded ? competitionRounds() : null, g.loaded ? garminRounds() : null, g.loaded ? garminRoundStats() : null]);
}

// One measure round by round: dots, the average of the last 5 rounds and of the last 10.
function roundChart(id, d) {
  const dates = d.points.map((p) => p.date);
  const solid = d.points.filter((p) => !p.derived), open = d.points.filter((p) => p.derived);
  const [short, long] = d.windows;
  const traces = [
    { x: solid.map((p) => p.date), y: solid.map((p) => p.value), mode: "markers", name: "rounds", marker: { size: 7, color: rgba("#378ADD", 0.5) },
      customdata: solid.map((p) => dateLabel(p.date)), hovertemplate: "%{customdata}: %{y:.1f}<extra></extra>" },
    { x: open.map((p) => p.date), y: open.map((p) => p.value), mode: "markers", name: "calculated", marker: { size: 8, symbol: "circle-open", color: "#378ADD", line: { width: 2 } },
      customdata: open.map((p) => dateLabel(p.date)), hovertemplate: "%{customdata}: %{y:.1f} (calculated)<extra></extra>", visible: open.length ? true : "legendonly", showlegend: open.length > 0 },
    { x: dates, y: d.points.map((p) => p.short), mode: "lines", line: { color: long ? rgba("#378ADD", 0.8) : css("--accent"), width: long ? 1.5 : 3 }, name: `last ${short} rounds`, connectgaps: false,
      hovertemplate: `last ${short} rounds: %{y:.1f}<extra></extra>` },
  ];
  if (long) {
    traces.push({ x: dates, y: d.points.map((p) => p.long), mode: "lines", line: { color: css("--accent"), width: 3.5 }, name: `last ${long} rounds`, connectgaps: false,
      hovertemplate: `last ${long} rounds: %{y:.1f}<extra></extra>` });
  }
  draw(id, traces, baseLayout({ xaxis: { type: "date", showgrid: true }, yaxis: { title: { text: d.title }, showgrid: true }, legend: { orientation: "h", y: 1.12 } }));
}

function roundNote(d) {
  const n = (v) => (v == null ? "–" : v.toFixed(1));
  const [short, long] = d.windows;
  return d.latest
    ? `${d.points.length} of ${d.rounds} rounds have a value. Latest: average of the last ${short} rounds ${n(d.latest.short)}`
      + (long ? `, of the last ${long} rounds ${n(d.latest.long)}` : "") + `; whole period ${n(d.latest.all)}.`
    : "No rounds with this measure in this period.";
}

// Which rounds take part: a tick per round, like the sessions. Rows are newest first.
const roundRows = { competition: [], garmin: [] };
const roundTimer = {};
const roundIds = { competition: "rc", garmin: "rg" };

function renderRoundCount(source) {
  const rows = roundRows[source];
  $(`${roundIds[source]}-count`).textContent = `${rows.filter((r) => r.selected).length} of ${rows.length} rounds selected`;
}

function selectRounds(source, predicate) {
  roundRows[source].forEach((r, i) => (r.selected = predicate(r, i)));
  source === "competition" ? renderCompetitionTable() : renderGarminList();
  saveRounds(source);
}

function saveRounds(source) {
  clearTimeout(roundTimer[source]);
  roundTimer[source] = setTimeout(guard(async () => {
    const selected = roundRows[source].filter((r) => r.selected).map((r) => r.key);
    if (!selected.length) { showError("Select at least one round."); return; }
    await api("/api/rounds/select", { body: { source, selected } });
    await (source === "competition" ? competitionRounds() : Promise.all([garminRounds(), garminRoundStats()]));
  }), 300);
}

function wireRoundSelection(source, tableId) {
  const id = roundIds[source];
  $(`${id}-all`).addEventListener("click", () => selectRounds(source, () => true));
  $(`${id}-year`).addEventListener("click", () => {
    const newest = roundRows[source].length ? new Date(roundRows[source][0].date + "T12:00:00") : new Date();
    selectRounds(source, (r) => (newest - new Date(r.date + "T12:00:00")) / 86400000 < 365);
  });
  $(`${id}-last`).addEventListener("click", () => selectRounds(source, (r, i) => i < 10));
  $(tableId).addEventListener("change", (event) => {
    const box = event.target.closest("input[type=checkbox]");
    if (!box) return;
    const row = roundRows[source].find((r) => r.key === box.dataset.key);
    if (row) { row.selected = box.checked; renderRoundCount(source); saveRounds(source); }
  });
}

const tick = (source, r) => `<td><input type="checkbox" data-key="${r.key.replace(/"/g, "&quot;")}"${r.selected ? " checked" : ""}></td>`;
const dim = (r, html) => (r.selected ? html : `<span style="opacity:.45">${html}</span>`);

function renderCompetitionTable() {
  const rows = roundRows.competition, withGarmin = roundGarminLinked;
  const g = (row, key, digits) => (row.garmin && row.garmin[key] != null ? num(row.garmin[key], digits) : "–");
  const body = rows.map((r) => `<tr>${tick("competition", r)}<td>${dim(r, dateLabel(r.date))}</td><td style="text-align:left">${dim(r, r.club)}</td><td>${dim(r, `${r.par}/${r.slope}/${num(r.rating)}`)}</td>`
    + `<td>${dim(r, r.gross_derived ? `<i title="calculated from the differential">${num(r.gross, 0)}*</i>` : num(r.gross, 0))}</td><td>${dim(r, num(r.stableford, 0))}</td><td>${dim(r, num(r.differential))}</td><td>${dim(r, num(r.hcp_new))}</td>`
    + (withGarmin ? `<td>${dim(r, g(r, "fir_pct", 0))}</td><td>${dim(r, g(r, "gir_pct", 0))}</td><td>${dim(r, g(r, "putts_per_hole", 2))}</td><td>${dim(r, g(r, "penalty_strokes", 0))}</td>` : "") + "</tr>");
  $("rc-table").innerHTML = "<tr><th></th><th>Date</th><th style='text-align:left'>Club</th><th>Par / slope / rating</th><th>Strokes</th><th>Stableford</th><th>Differential</th><th>Handicap after</th>"
    + (withGarmin ? "<th>Fairways hit %</th><th>GIR %</th><th>Putts per hole</th><th>Penalties</th>" : "") + "</tr>"
    + (body.join("") || '<tr><td colspan="12" class="muted">No rounds.</td></tr>');
  renderRoundCount("competition");
}

let roundGarminLinked = false;

async function competitionRounds() {
  const period = $("rc-period").value;
  const [d, t] = await Promise.all([
    api("/api/rounds/trend", { params: { source: "competition", measure: $("rc-measure").value, period } }),
    api("/api/rounds/competition"),
  ]);
  roundChart("rc-plot", d);
  $("rc-note").textContent = roundNote(d);
  roundRows.competition = t.rows;
  roundGarminLinked = t.garmin_loaded;
  renderCompetitionTable();
  const derived = t.rows.filter((r) => r.gross_derived).length;
  $("rc-table-note").textContent = (derived ? `* strokes calculated from the differential, the course rating, the slope and the PCC, because the certificate does not list them (${derived}). ` : "")
    + (t.garmin_loaded ? `The last four columns are the statistics of a Garmin round on the same day: ${t.linked} of ${t.rows.length} competition rounds have one.` : "");
}

function renderGarminList() {
  const body = roundRows.garmin.map((r) => `<tr>${tick("garmin", r)}<td>${dim(r, dateLabel(r.date))}</td><td style="text-align:left">${dim(r, r.course)}</td><td>${dim(r, r.tee)}</td>`
    + `<td>${dim(r, num(r.strokes, 0))}</td><td>${dim(r, num(r.to_par, 0))}</td><td>${dim(r, num(r.differential))}</td>`
    + `<td>${dim(r, num(r.fir_pct, 0))}</td><td>${dim(r, num(r.gir_pct, 0))}</td><td>${dim(r, num(r.putts_per_hole, 2))}</td><td>${dim(r, num(r.penalty_strokes, 0))}</td></tr>`).join("");
  $("rl-table").innerHTML = "<tr><th></th><th>Date</th><th style='text-align:left'>Course</th><th>Tee</th><th>Strokes</th><th>To par</th><th>Differential</th><th>Fairways hit %</th><th>GIR %</th><th>Putts per hole</th><th>Penalties</th></tr>"
    + (body || '<tr><td colspan="11" class="muted">No rounds.</td></tr>');
  $("rl-note").textContent = "A dash means the round has too little data for that statistic.";
  renderRoundCount("garmin");
}

async function garminRounds() {
  const [d, t] = await Promise.all([
    api("/api/rounds/trend", { params: { source: "garmin", measure: $("rg-measure").value, period: $("rg-period").value } }),
    api("/api/rounds/garmin-rounds"),
  ]);
  roundChart("rg-plot", d);
  $("rg-note").textContent = roundNote(d);
  roundRows.garmin = t.rows;
  renderGarminList();
}

async function garminRoundStats() {
  const s = await api("/api/rounds/garmin-summary");
  $("rs-table").innerHTML = `<tr><th>Statistic</th>${s.columns.map((c) => `<th>${c.title}<br><span class="pm">${c.rounds} rounds</span></th>`).join("")}</tr>`
    + s.rows.map((r) => `<tr><td>${r.title}</td>${s.columns.map((c) => `<td>${r.values[c.key] == null ? "–" : r.values[c.key]}</td>`).join("")}</tr>`).join("");
  $("rs-note").textContent = s.first ? `Selected full 18-hole rounds from ${dateLabel(s.first)} to ${dateLabel(s.last)}. Each percentage is calculated over all holes that have the data, not as the average of the rounds.` : "No round is selected.";
}

// ---------------------------------------------------------------- Garmin

function garminParams() {
  const outcome = $("gm-outcome").value;
  const club = outcome.startsWith("swing") ? $("gm-club").value : "";
  return { outcome, club, detrend: $("gm-detrend").checked ? "1" : "0" };
}

async function loadGarmin() {
  const o = await api("/api/garmin/overview");
  const compared = o.outcomes.length > 0;                                   // Garmin alone: only the plot of the Garmin measures
  for (const id of ["gm-results-card", "gm-scatter-card", "gm-howto-card"]) $(id).hidden = !compared;
  fillSelect($("gm-outcome"), o.outcomes.map((x) => x.key), o.outcomes.map((x) => x.title));
  fillSelect($("gm-club"), ["", ...o.clubs], ["All clubs together", ...o.clubs]);
  fillMeasureMenu($("gm-predictor"), o.predictors, "sleep_h");
  fillMeasureMenu($("gp-x"), o.daily, "strength_min_24h");
  fillMeasureMenu($("gp-y"), o.daily, "sleep_score");
  const periods = [["all", "All data"], ...o.days.map((n) => [`days:${n}`, n === 90 ? "Last 3 months" : n === 365 ? "Last 12 months" : `Last ${n} days`]),
    ...o.years.map((y) => [`year:${y}`, String(y)])];
  $("ts-card").hidden = !o.training_sleep;
  for (const id of ["gp-period", "ht-period", "ts-period"]) fillSelect($(id), periods.map((p) => p[0]), periods.map((p) => p[1]));
  fillMeasureMenu($("ht-measure"), o.daily, "hrv_ms");
  await Promise.all([compared ? garminRefresh() : null, garminPair(), healthTrend(), o.training_sleep ? trainingSleep() : null]);
}

async function garminRefresh() {
  $("gm-club-label").hidden = !$("gm-outcome").value.startsWith("swing");
  await Promise.all([garminForest(), garminScatter()]);
}

let forestBound = false;

async function garminForest() {
  if (!$("gm-outcome").value) return;
  const d = await api("/api/garmin/table", { params: garminParams() });
  const rows = d.rows;
  const names = rows.map((r) => `${r.title}  (n=${r.n})`);
  const tested = rows.filter((r) => r.r !== null);
  const accent = css("--accent");
  const traces = [
    {
      x: tested.flatMap((r) => [r.low, r.high, null]), y: tested.flatMap((r) => [`${r.title}  (n=${r.n})`, `${r.title}  (n=${r.n})`, null]),
      mode: "lines", line: { color: rgba("#378ADD", 0.45), width: 9 }, hoverinfo: "skip", showlegend: false,
    },
    {
      x: tested.map((r) => r.r), y: tested.map((r) => `${r.title}  (n=${r.n})`), mode: "markers", showlegend: false,
      marker: { size: 9, color: accent }, customdata: tested.map((r) => [r.key, r.low, r.high]),
      hovertemplate: "r = %{x:.2f}  (%{customdata[1]:.2f} to %{customdata[2]:.2f})<extra></extra>",
    },
  ];
  $("gm-forest").style.height = Math.max(300, 30 * rows.length + 90) + "px";
  draw("gm-forest", traces, baseLayout({
    margin: { l: 300, r: 16, t: 10, b: 44 },
    xaxis: { title: { text: `Correlation with the result (r), with its ${Math.round(d.level * 100)}% interval` }, range: [-1, 1], zeroline: true, zerolinewidth: 2, showgrid: true },
    yaxis: { type: "category", categoryorder: "array", categoryarray: names, autorange: "reversed", showgrid: true },
  }));
  if (!forestBound) {
    forestBound = true;
    $("gm-forest").on("plotly_click", (event) => {
      const key = event.points[0].customdata && event.points[0].customdata[0];
      if (key) { $("gm-predictor").value = key; guard(garminScatter)(); }
    });
  }
  const chance = (1 - d.level) * d.tested;
  $("gm-forest-note").textContent = `${d.title}. ${d.sessions} sessions. ${d.clear} of ${d.tested} measures have a bar that does not cross zero; `
    + `with this many measures about ${chance.toFixed(1)} would do so by chance alone. Measures without a dot have fewer than 5 sessions with a value (body measures need a weighing in the 14 days before the session).`;
}

async function garminScatter() {
  if (!$("gm-outcome").value || !$("gm-predictor").value) return;
  const d = await api("/api/garmin/scatter", { params: { ...garminParams(), predictor: $("gm-predictor").value } });
  const traces = [{
    x: d.points.map((p) => p.x), y: d.points.map((p) => p.y), mode: "markers", showlegend: false,
    marker: { size: 11, color: css("--accent") }, customdata: d.points.map((p) => dateLabel(p.date)),
    hovertemplate: `${d.x_title}: %{x:.1f}<br>result: %{y:.1f}<br>%{customdata}<extra></extra>`,
  }];
  if (d.fit) {
    const xs = d.points.map((p) => p.x);
    const lo = Math.min(...xs), hi = Math.max(...xs);
    traces.push({ x: [lo, hi], y: [d.fit.slope * lo + d.fit.intercept, d.fit.slope * hi + d.fit.intercept], mode: "lines",
      line: { color: css("--muted"), dash: "dash", width: 2 }, hoverinfo: "skip", showlegend: false });
  }
  draw("gm-plot", traces, baseLayout({ xaxis: { title: { text: d.x_title }, showgrid: true }, yaxis: { title: { text: d.y_title }, showgrid: true, zeroline: true } }));
  const pct = Math.round(d.level * 100);
  $("gm-note").textContent = d.fit
    ? `${d.fit.n} of ${d.sessions} sessions. Correlation r = ${d.fit.r.toFixed(2)}, ${pct}% interval ${d.fit.low.toFixed(2)} to ${d.fit.high.toFixed(2)}. `
      + (d.fit.low < 0 && d.fit.high > 0 ? "The interval includes zero, so this could be chance." : "The interval does not include zero, but with many measures tried some will look like this by chance.")
    : `${d.points.length} of ${d.sessions} sessions have this measure: too few, or no variation, for a correlation.`;
}

async function healthTrend() {
  if (!$("ht-measure").value) return;
  const d = await api("/api/health/trend", { params: { measure: $("ht-measure").value, period: $("ht-period").value } });
  const dates = d.points.map((p) => p.date);
  const accent = css("--accent");
  const [short, long] = d.windows;
  $("ht-help").textContent = `Every day of your Garmin and Withings exports. The dots are single values (one night, one weighing), the thin line is the average of the last ${short} days and the bold line `
    + `the average of the last ${long} days, so the bold line shows where you are heading. An average is only drawn where its window holds enough values.`;
  const traces = [
    { x: dates, y: d.points.map((p) => p.value), mode: "markers", marker: { size: 5, color: rgba("#378ADD", 0.35) }, name: "single values",
      customdata: dates.map(dateLabel), hovertemplate: "%{customdata}: %{y:.1f}<extra></extra>" },
    { x: dates, y: d.points.map((p) => p.short), mode: "lines", line: { color: rgba("#378ADD", 0.8), width: 1.5 }, name: `${short}-day average`, connectgaps: false,
      hovertemplate: `${short}-day average %{y:.1f}<extra></extra>` },
    { x: dates, y: d.points.map((p) => p.long), mode: "lines", line: { color: accent, width: 3.5 }, name: `${long}-day average`, connectgaps: false,
      hovertemplate: `${long}-day average %{y:.1f}<extra></extra>` },
  ];
  draw("ht-plot", traces, baseLayout({ xaxis: { type: "date", showgrid: true }, yaxis: { title: { text: d.title }, showgrid: true }, legend: { orientation: "h", y: 1.12 } }));
  const n = (v) => (v == null ? "–" : v.toFixed(1));
  $("ht-note").textContent = d.latest
    ? `${d.points.length} of ${d.days} days have a value. Latest: ${short}-day average ${n(d.latest.short)}, ${long}-day average ${n(d.latest.long)}; whole period ${n(d.latest.all)}.`
    : "No values for this measure in this period.";
}

async function trainingSleep() {
  const d = await api("/api/health/training-sleep", { params: { period: $("ts-period").value } });
  const cell = (c) => `${num(c.mean, 1)} <span class="pm">n=${c.n}</span>`;
  const change = (c) => {
    if (c.diff == null) return "–";
    const text = `${signed(c.diff, 1)} <span class="pm">(${signed(c.low, 1)} to ${signed(c.high, 1)})</span>`;
    return c.low > 0 || c.high < 0 ? `<b>${text}</b>` : text;
  };
  const rows = d.rows.map((r) => `<tr><td>${r.title}</td><td>${cell(r.none)}</td><td>${cell(r.earlier)}</td><td>${change(r.earlier)}</td><td>${cell(r.late)}</td><td>${change(r.late)}</td></tr>`).join("");
  $("ts-table").innerHTML = `<tr><th rowspan="2">Measure</th><th>No training in 12 h</th><th colspan="2">Training 4 to 12 h before bed</th><th colspan="2">Training within 4 h before bed</th></tr>`
    + `<tr><th>average</th><th>average</th><th>difference</th><th>average</th><th>difference</th></tr>` + rows;
  const pct = Math.round(d.level * 100);
  const cells = d.rows.flatMap((r) => [r.earlier, r.late]).filter((c) => c.diff != null);
  const clear = cells.filter((c) => c.low > 0 || c.high < 0).length;
  $("ts-note").textContent = d.nights
    ? `${d.nights} nights: ${d.groups[0].nights} without training, ${d.groups[1].nights} with training 4 to 12 h before bed, ${d.groups[2].nights} within 4 h. ${pct}% intervals. `
      + `${clear} of ${cells.length} differences are clear; about ${((1 - d.level) * cells.length).toFixed(1)} would be by chance alone. This is an association: days with an evening workout also differ in other ways.`
    : "No nights in this period.";
}

async function garminPair() {
  if (!$("gp-x").value || !$("gp-y").value) return;
  const d = await api("/api/garmin/pair", { params: { x: $("gp-x").value, y: $("gp-y").value, period: $("gp-period").value } });
  const times = d.points.map((p) => Date.parse(p.date));
  const first = Math.min(...times), last = Math.max(...times);
  const ticks = times.length ? [0, 1, 2, 3].map((i) => first + ((last - first) * i) / 3) : [];
  const traces = [{
    x: d.points.map((p) => p.x), y: d.points.map((p) => p.y), mode: "markers", showlegend: false,
    marker: { size: 7, color: times, colorscale: "Viridis", opacity: 0.75, colorbar: { thickness: 10, len: 0.8, tickvals: ticks, ticktext: ticks.map((v) => dateLabel(new Date(v).toISOString().slice(0, 10))), tickfont: { size: 10 } } },
    customdata: d.points.map((p) => dateLabel(p.date)),
    hovertemplate: `${d.x_title}: %{x:.1f}<br>${d.y_title}: %{y:.1f}<br>%{customdata}<extra></extra>`,
  }];
  if (d.fit) {
    const xs = d.points.map((p) => p.x);
    const lo = Math.min(...xs), hi = Math.max(...xs);
    traces.push({ x: [lo, hi], y: [d.fit.slope * lo + d.fit.intercept, d.fit.slope * hi + d.fit.intercept], mode: "lines",
      line: { color: css("--muted"), dash: "dash", width: 2 }, hoverinfo: "skip", showlegend: false });
  }
  draw("gp-plot", traces, baseLayout({ xaxis: { title: { text: d.x_title }, showgrid: true }, yaxis: { title: { text: d.y_title }, showgrid: true } }));
  const pct = Math.round(d.level * 100);
  $("gp-note").textContent = $("gp-x").value === $("gp-y").value ? "Choose two different measures."
    : d.fit
    ? `${d.fit.n} of ${d.days} days (${dateLabel(d.first)} to ${dateLabel(d.last)}). Correlation r = ${d.fit.r.toFixed(2)}, ${pct}% interval ${d.fit.low.toFixed(2)} to ${d.fit.high.toFixed(2)}. `
      + "A correlation shows that two measures go together, not that one causes the other."
    : `${d.points.length} of ${d.days} days have both measures: too few, or no variation, for a correlation.`;
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

const refreshers = { sessions: loadSessions, swing: loadSwing, pitching: loadPitching, stack: loadStack, rounds: loadRounds, garmin: loadGarmin, bag: loadBag, wedges: loadWedges };

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
  $("browse-stack").addEventListener("click", guard(() => browse("stack")));
  $("browse-garmin").addEventListener("click", guard(() => browse("garmin")));
  $("browse-withings").addEventListener("click", guard(() => browse("withings")));
  $("browse-competition").addEventListener("click", guard(() => browse("competition")));
  wireRoundSelection("competition", "rc-table");
  wireRoundSelection("garmin", "rl-table");
  for (const id of ["st-avg", "st-max"]) $(id).addEventListener("change", guard(loadStack));
  for (const id of ["rc-measure", "rc-period"]) $(id).addEventListener("change", guard(competitionRounds));
  for (const id of ["rg-measure", "rg-period"]) $(id).addEventListener("change", guard(garminRounds));
  for (const id of ["gm-outcome", "gm-club", "gm-detrend"]) $(id).addEventListener("change", guard(garminRefresh));
  $("gm-predictor").addEventListener("change", guard(garminScatter));
  for (const id of ["ht-measure", "ht-period"]) $(id).addEventListener("change", guard(healthTrend));
  $("ts-period").addEventListener("change", guard(trainingSleep));
  for (const id of ["gp-x", "gp-y", "gp-period"]) $(id).addEventListener("change", guard(garminPair));

  for (const id of ["sw-session", "sw-baseline"]) $(id).addEventListener("change", guard(swingReview));
  for (const id of ["sw-club", "sw-metric"]) $(id).addEventListener("change", guard(swingProgress));
  for (const id of ["sw-disp-club", "sw-disp-session", "sw-disp-compare"]) $(id).addEventListener("change", guard(swingDispersion));
  $("lv-club").addEventListener("change", guard(swingLevers));
  $("sw-card").addEventListener("click", guard(() => makeCard("swing", "sw")));

  for (const id of ["pt-session", "pt-baseline"]) $(id).addEventListener("change", guard(pitchingReview));
  for (const id of ["sc-club", "sc-x", "sc-y", "sc-fit"]) $(id).addEventListener("change", guard(pitchingScatter));
  $("pt-club").addEventListener("change", guard(async () => { fillIntents(); await pitchingProgress(); }));
  for (const id of ["pt-intent", "pt-metric"]) $(id).addEventListener("change", guard(pitchingProgress));
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
  const first = firstAvailableTab();
  if (first) await showTab(first);
})();
