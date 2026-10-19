// Draws a review result: score heads with a band scale, where points were lost, next actions,
// comments anchored to the transcript, and the full report folded away.
// Pure DOM building with textContent only: quotes and reasons come from the model and the
// transcript, so nothing here goes through innerHTML. Positions are set through CSSOM
// (el.style), which the page's CSP (style-src 'self') allows.

const TRACKS = ["meeting", "self"];

function h(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text != null) el.textContent = text;
  return el;
}

const fill = (s, vars) => s.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "");

/** 0..100 bands from the config, lowest first: [{id, min, max}]. */
function bandRanges(bands) {
  const sorted = [...bands].sort((a, b) => a.min - b.min);
  return sorted.map((b, k) => ({ id: b.id, min: b.min, max: k + 1 < sorted.length ? sorted[k + 1].min : 100 }));
}

/**
 * Points lost per criterion on the 0-100 scale, plus the time overrun as id "time_overrun",
 * rounded (largest remainder) so that the rows add up to exactly 100 - score. When the rows add up
 * to more than that (the score was rounded up, or clamped at 0), the criteria are scaled down. Criteria without a level
 * are left out, because score.py drops them from the denominator.
 */
export const TIME = "time_overrun";
export function lostPoints(track) {
  const scored = track.breakdown.filter((r) => r.level != null);
  const possible = scored.reduce((s, r) => s + r.weight, 0);
  if (!possible || track.score == null) return [];
  const exact = scored.map((r) => ({ id: r.id, level: r.level, value: ((r.weight - r.weight * r.level / 4) * 100) / possible }));
  for (const p of track.penalties) if (p.points > 0) exact.push({ id: TIME, overrun: p.overrun_ratio, value: p.points });
  const target = 100 - track.score;
  const sum = exact.reduce((s, r) => s + r.value, 0);
  if (sum > target) {
    // rounded up or clamped at 0: the time penalty keeps its real size (the report states it), criteria share the rest
    const time = exact.filter((r) => r.id === TIME).reduce((s, r) => s + r.value, 0);
    const room = Math.max(0, target - time);
    for (const r of exact) if (r.id !== TIME) r.value = (r.value * room) / (sum - time || 1);
  }
  const rows = exact.map((r) => ({ ...r, lost: Math.floor(r.value + 1e-9) }));
  let left = target - rows.reduce((s, r) => s + r.lost, 0);
  const frac = (k) => exact[k].value - rows[k].lost;
  const order = rows.map((r, k) => k).sort((x, y) => frac(y) - frac(x));
  for (const k of order) {
    if (left <= 0) break;
    if (frac(k) > 1e-9) { rows[k].lost += 1; left -= 1; }
  }
  return rows;
}

function clock(sec) {
  if (sec == null || Number.isNaN(sec)) return "";
  const s = Math.max(0, Math.floor(sec));
  const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
  const p = (n) => String(n).padStart(2, "0");
  return hh ? `${hh}:${p(mm)}:${p(ss)}` : `${p(mm)}:${p(ss)}`;
}

// ---------------------------------------------------------------- score head

function scoreHead(trackName, track, ctx) {
  const { labels, t, bands } = ctx;
  const sec = h("section", "track");
  sec.append(h("h3", "track-name", labels[trackName]));
  const top = h("div", "track-top");
  const num = h("p", "track-score");
  num.append(h("span", "num", track.score ?? "–"), h("span", "of", t("res_of")));
  top.append(num);
  if (track.band) {
    const chip = h("p", "band-chip");
    chip.append(h("b", null, track.band), document.createTextNode(` ${labels.bands[track.band] ?? ""}`));
    top.append(chip);
  }
  sec.append(top);

  if (track.score != null) {
    const ranges = bandRanges(bands);
    const scale = h("div", "scale");
    scale.setAttribute("role", "img");
    const bar = h("div", "scale-bar");
    for (const r of ranges) {
      const seg = h("div", `seg${r.id === track.band ? " current" : ""}`);
      seg.style.flexBasis = `${r.max - r.min}%`;
      seg.append(h("span", "seg-id", r.id));
      bar.append(seg);
    }
    const marker = h("div", "marker");
    marker.style.left = `${Math.min(100, Math.max(0, track.score))}%`;
    bar.append(marker);
    const ticks = h("div", "scale-ticks");
    for (const r of ranges.slice(1)) {
      const tick = h("span", null, r.min);
      tick.style.left = `${r.min}%`;
      ticks.append(tick);
    }
    scale.append(bar, ticks);
    const next = ranges.find((r) => r.min > track.score);
    const gap = next ? next.min - track.score : 0;
    const nextText = next ? fill(t(gap === 1 ? "res_next_1" : "res_next"), { b: next.id, n: gap }) : t("res_top");
    scale.setAttribute("aria-label", `${track.score}${t("res_of")}  ${track.band} ${labels.bands[track.band] ?? ""}  ${nextText}`);
    sec.append(scale, h("p", "next-band", nextText));
  }
  if (track.low_confidence) {
    const why = trackName === "self" && ctx.inferred ? labels.speakers_inferred : labels.low_confidence;
    sec.append(h("p", "note", why));
  }

  sec.append(lostList(track, ctx));
  return sec;
}

function levelBoxes(level) {
  const wrap = h("span", "levels");
  for (let k = 0; k < 4; k++) wrap.append(h("span", k < level ? "lv on" : "lv"));
  wrap.append(h("span", "lv-text", `${level}/4`));
  return wrap;
}

function lostList(track, ctx) {
  const { labels, t } = ctx;
  const box = h("div", "lost");
  const name = (id) => labels.criteria[id] ?? id;
  const sep = ctx.lang === "ja" ? "、" : ", ";
  const ns = track.breakdown.filter((r) => r.level == null).map((r) => name(r.id));
  if (track.score != null) {
    box.append(h("h4", null, t("res_lost")));
    const rows = lostPoints(track).filter((r) => r.lost > 0).sort((a, b) => b.lost - a.lost);
    const max = Math.max(1, ...rows.map((r) => r.lost));
    if (!rows.length) box.append(h("p", "note", t("res_no_loss")));
    const list = h("ul", "lost-list");
    for (const r of rows) {
      const li = h("li");
      const head = h("div", "lost-head");
      const detail = r.id === TIME ? h("span", "lv-text", `+${Math.round(+((r.overrun || 0) * 100).toFixed(6))}%`) : levelBoxes(r.level);
      head.append(h("span", "lost-name", r.id === TIME ? t("res_time") : name(r.id)), detail, h("span", "lost-pts", `−${r.lost}`));
      const meter = h("div", "lost-meter");
      const fillEl = h("div", "lost-fill");
      fillEl.style.width = `${(r.lost / max) * 100}%`;
      meter.append(fillEl);
      li.append(head, meter);
      list.append(li);
    }
    if (rows.length) box.append(list);
    if (ctx.penaltySkipped && track === ctx.selfTrack) box.append(h("p", "aside", labels.time_penalty_not_applied));
    const full = track.breakdown.filter((r) => r.level === 4).map((r) => name(r.id));
    if (full.length) box.append(h("p", "aside", `${t("res_full")}: ${full.join(sep)}`));
  }
  if (ns.length) box.append(h("p", "aside", `${t("res_ns")}: ${ns.join(sep)}`));
  return box;
}

// ---------------------------------------------------------------- comments

// Comparison form used by verify_evidence.py: NFKC and lower-case.
// ja drops exactly common.py's _PUNCT (Python's \s is JS \s plus \x1c-\x1f and \x85, minus \uFEFF);
// other languages keep words apart with single spaces so a quote only matches whole words.
const DROP = /(?!\uFEFF)[\s\x1c-\x1f\x85、。，,．.!！?？「」『』（）()\[\]【】…・\-—–"'“”‘’:：;；〜~]/u;
const KEEP_WORD = /[\p{L}\p{N}_']/u; // Python's \w, as verify_evidence.py splits words
const COMBINING = /[\p{M}ﾞﾟ]/u;
const ELLIPSIS = /…+|\.\.\.+|‥+/;

/**
 * Normalised text plus, for each normalised character, the source range [a, b) it came from.
 * A character and the marks after it (dakuten, half-width ﾞ) are normalised together so they compose.
 */
function normWithMap(text, words = false) {
  const units = [];
  let k = 0;
  for (const ch of text) {
    if (units.length && COMBINING.test(ch)) units[units.length - 1].s += ch;
    else units.push({ s: ch, a: k });
    k += ch.length;
    units[units.length - 1].b = k;
  }
  let norm = words ? " " : "";
  const map = words ? [[0, 0]] : [];
  for (const u of units) {
    for (const c of u.s.normalize("NFKC").toLowerCase()) {
      // one map entry per UTF-16 unit, so indices into norm stay aligned past astral characters
      if (words ? KEEP_WORD.test(c) : !DROP.test(c)) { norm += c; for (let j = 0; j < c.length; j++) map.push([u.a, u.b]); }
      else if (words && !norm.endsWith(" ")) { norm += " "; map.push([u.a, u.b]); }
    }
  }
  if (words && !norm.endsWith(" ")) { norm += " "; map.push([k, k]); }
  return { norm, map };
}

/** Source ranges [a, b) of a quote; null when any piece is not found (as verify would fail). */
function quoteRanges(text, quote, words = false) {
  const { norm, map } = normWithMap(text, words);
  const out = [];
  let from = 0;
  for (const raw of quote.split(ELLIPSIS)) {
    let piece = normWithMap(raw, words).norm;
    if (!piece.trim()) continue;
    if (words) piece = ` ${piece.trim()} `;
    const at = norm.indexOf(piece, from);
    if (at < 0) return null;
    // in word mode the needle is padded with the spaces around it; mark only the words
    const [s, e] = words ? [at + 1, at + piece.length - 2] : [at, at + piece.length - 1];
    out.push([map[s][0], map[e][1]]);
    from = words ? at + piece.length - 1 : at + piece.length;
  }
  return out.length ? out : null;
}

/** Text with <mark> over the quoted ranges; each comment number appears once, where its quote ends. */
function markedText(text, spans) {
  const cuts = [...new Set([0, text.length, ...spans.flatMap((s) => [s.a, s.b])])].sort((x, y) => x - y);
  const frag = document.createDocumentFragment();
  for (let k = 0; k + 1 < cuts.length; k++) {
    const [a, b] = [cuts[k], cuts[k + 1]];
    const piece = text.slice(a, b);
    if (!spans.some((s) => s.a < b && s.b > a)) { frag.append(piece); continue; }
    const mark = h("mark", null, piece);
    const ending = [...new Set(spans.filter((s) => s.b === b && s.last).map((s) => s.n))].sort((x, y) => x - y);
    if (ending.length) mark.append(h("sup", "ref", ending.join(",")));
    frag.append(mark);
  }
  return frag;
}

function utteranceLine(u, ctx, marks = [], missing = null) {
  // ja ignores spaces when matching; a full-width space only keeps the backchannel readable
  const lead = u.lead_backchannel;
  const sep = ctx.words ? " " : lead && /[\p{P}\s]$/u.test(lead) ? "" : "\u3000";
  const text = [lead, u.text].filter(Boolean).join(sep);
  const spans = [];
  for (const m of marks) {
    const ranges = quoteRanges(text, m.quote, ctx.words);
    if (!ranges) { missing?.add(m.n); continue; }
    ranges.forEach(([a, b], k) => spans.push({ a, b, n: m.n, last: k === ranges.length - 1 }));
  }
  const li = h("li", `utt${spans.length ? " hit" : ""}`);
  const who = h("p", "utt-who");
  const speaker = u.speaker || "?";
  who.append(h("span", "speaker", u.speaker && u.speaker === ctx.me ? `${speaker} (${ctx.labels.me})` : speaker));
  if (u.start != null) who.append(h("span", "time", clock(u.start)));
  const body = h("p", "utt-text");
  body.append(markedText(text, spans));
  li.append(who, body);
  return li;
}

/** Everything that deserves a comment, grouped by where it points in the transcript. */
function collectComments(result, judgement, ctx) {
  const { labels, t } = ctx;
  const tips = {};
  for (const imp of judgement.improvements || []) if (imp.criterion && imp.try_instead) tips[imp.criterion] ??= imp.try_instead;
  const lost = {};
  for (const tr of TRACKS) for (const r of lostPoints(result[tr])) lost[r.id] = r.lost;

  const groups = new Map();
  const add = (key, sort, anchor, item) => {
    if (!groups.has(key)) groups.set(key, { sort, anchor, items: [] });
    groups.get(key).items.push(item);
  };
  for (const c of judgement.criteria || []) {
    if (c.level == null || c.level >= 4) continue;
    const base = { title: labels.criteria[c.id] ?? c.id, lost: lost[c.id] ?? 0, reason: c.reason, tip: tips[c.id], kind: "criterion", id: c.id };
    for (const e of c.evidence || []) {
      // absence first, in the same order verify_evidence.py checks them
      if ("absence" in e) { if (Array.isArray(e.range)) add(`a${e.range[0]}-${e.range[1]}`, e.range[0], { range: e.range }, { ...base, absence: e.absence }); }
      else if (e.quote != null && Number.isInteger(e.i)) add(`q${e.i}`, e.i, { i: e.i }, { ...base, i: e.i, quote: e.quote });
    }
  }
  for (const s of judgement.signals || []) {
    if (s.verdict !== "risk") continue;
    const base = { title: t(`sig_${s.type}`), kind: "signal", reason: s.reason };
    if ("absence" in s) { if (Array.isArray(s.range)) add(`a${s.range[0]}-${s.range[1]}`, s.range[0], { range: s.range }, { ...base, absence: s.absence }); }
    else if (s.quote != null && Number.isInteger(s.i)) add(`q${s.i}`, s.i, { i: s.i }, { ...base, i: s.i, quote: s.quote });
  }
  // quote groups whose context lines touch are drawn as one excerpt, so a line never repeats
  const list = [];
  let prev = null; // the last quote group, so an absence in between does not stop the merge
  for (const g of [...groups.values()].sort((a, b) => a.sort - b.sort)) {
    if (g.anchor.i != null && prev && g.anchor.i - 1 <= prev.anchor.hi + 1) {
      prev.anchor.hits.push(g.anchor.i);
      prev.anchor.hi = g.anchor.i + 1;
      prev.items.push(...g.items);
      continue;
    }
    if (g.anchor.i != null) { g.anchor = { hits: [g.anchor.i], lo: g.anchor.i - 1, hi: g.anchor.i + 1 }; prev = g; }
    list.push(g);
  }
  let n = 0;
  for (const g of list) {
    // in transcript order; on the same line criteria first (largest loss first), then signals
    const rank = (it) => [it.i ?? -1, it.kind === "criterion" ? 0 : 1, -(it.lost ?? 0)];
    g.items.sort((a, b) => { const x = rank(a), y = rank(b); return x[0] - y[0] || x[1] - y[1] || x[2] - y[2]; });
    for (const it of g.items) it.n = ++n;
  }
  // a criterion with several pieces of evidence shows its points once, on its first card
  const shown = new Set();
  for (const g of list) for (const it of g.items) {
    if (it.kind !== "criterion") continue;
    if (shown.has(it.id)) it.lost = 0; else shown.add(it.id);
  }
  return list;
}

function commentCard(it, ctx) {
  const { t } = ctx;
  const card = h("li", `note-card ${it.kind}`);
  const head = h("p", "note-head");
  head.append(h("span", "ref-n", String(it.n)));
  head.append(h("span", "note-title", it.kind === "signal" ? `${t("res_signal")}: ${it.title}` : it.title));
  if (it.lost) head.append(h("span", "note-pts", `−${it.lost} ${t(it.lost === 1 ? "res_pts_1" : "res_pts")}`));
  card.append(head);
  if (it.absence) card.append(h("p", "note-absence", `${t("res_absence")}: ${it.absence}`));
  if (it.missing) card.append(h("p", "note-absence", `${t("res_quote_missing")}: ${it.quote}`));
  if (it.reason) card.append(h("p", "note-reason", it.reason));
  if (it.tip) {
    const tip = h("p", "note-tip");
    tip.append(h("b", null, `${t("res_try")}: `), document.createTextNode(it.tip));
    card.append(tip);
  }
  return card;
}

function commentsSection(result, judgement, transcript, ctx) {
  const { t } = ctx;
  const groups = collectComments(result, judgement, ctx);
  const sec = h("section", "comments");
  sec.append(h("h3", null, t("res_comments")), h("p", "note", t("res_comments_hint")));
  const utts = transcript?.utterances || [];
  const at = (i) => utts.find((u) => u.i === i) ?? utts[i];
  const shownLines = new Set();
  for (const g of groups) if (g.anchor.hits) for (let i = g.anchor.lo; i <= g.anchor.hi; i++) if (at(i)) shownLines.add(i);
  // same default as verify_evidence.py
  ctx = { ...ctx, words: (transcript?.language ?? "en") !== "ja" };
  for (const g of groups) {
    const row = h("div", "cmt-row");
    const excerpt = h("ol", "excerpt");
    const missing = new Set();
    if (g.anchor.hits) {
      for (let i = g.anchor.lo; i <= g.anchor.hi; i++) {
        const u = at(i);
        const marks = g.items.filter((it) => it.quote && it.i === i).map((it) => ({ quote: it.quote, n: it.n }));
        if (u) excerpt.append(utteranceLine(u, ctx, marks, missing));
        else for (const m of marks) missing.add(m.n);
      }
      for (const it of g.items) if (missing.has(it.n)) it.missing = true;
    } else {
      const [a, b] = g.anchor.range;
      excerpt.classList.add("stretch");
      const first = at(a), last = at(b);
      // an end line already drawn in a quote excerpt is not repeated; it counts as skipped here
      const showFirst = first && (a === b || !shownLines.has(a));
      const showLast = last && b !== a && !shownLines.has(b);
      const skipped = b - a + 1 - (showFirst ? 1 : 0) - (showLast ? 1 : 0);
      if (showFirst) excerpt.append(utteranceLine(first, ctx));
      if (skipped > 0) excerpt.append(h("li", "utt-gap", skipped === 1 ? t("res_skipped_1") : fill(t("res_skipped"), { n: skipped })));
      if (showLast) excerpt.append(utteranceLine(last, ctx));
      if (showFirst) shownLines.add(a);
      if (showLast) shownLines.add(b);
      const span = [first?.start, last?.end ?? last?.start].filter((x) => x != null);
      if (span.length === 2) excerpt.prepend(h("li", "utt-range", `${clock(span[0])} – ${clock(span[1])}`));
    }
    const notes = h("ul", "notes");
    for (const it of g.items) notes.append(commentCard(it, ctx));
    row.append(excerpt, notes);
    sec.append(row);
  }
  return groups.length ? sec : null;
}

// ---------------------------------------------------------------- whole result

/**
 * @param {object} p
 * @param {object} p.result       score.py compute() output
 * @param {object} p.judgement    normalised judgement (criteria, signals, improvements, next_actions)
 * @param {object} p.transcript   parsed transcript (utterances)
 * @param {object} p.labels       locale labels (scripts/locales/{lang}.json → labels)
 * @param {Function} p.t          UI string lookup
 * @param {Array} p.bands         config bands [{id, min}]
 * @param {string} p.lang
 * @param {string} [p.me]         the user's speaker name
 * @param {Node} [p.report]       already-sanitised report body
 * @returns {Node[]}
 */
export function renderResult(p) {
  const ctx = {
    labels: p.labels, t: p.t, bands: p.bands, lang: p.lang, me: p.me,
    inferred: p.result.speakers_inferred, selfTrack: p.result.self,
    penaltySkipped: p.result.time_penalty_points > 0 && p.result.self?.score != null && !p.result.self.penalties.length,
  };
  const parts = [];
  const heads = h("div", "tracks");
  for (const tr of TRACKS) if (p.result[tr]) heads.append(scoreHead(tr, p.result[tr], ctx));
  parts.push(heads);

  const actions = (p.judgement?.next_actions || []).map((a) => a.text).filter(Boolean);
  if (actions.length) {
    const sec = h("section", "next-actions");
    sec.append(h("h3", null, p.t("res_actions")));
    const ol = h("ol");
    for (const a of actions) ol.append(h("li", null, a));
    sec.append(ol);
    parts.push(sec);
  }

  const comments = p.judgement ? commentsSection(p.result, p.judgement, p.transcript, ctx) : null;
  if (comments) parts.push(comments);

  if (p.report) {
    const det = h("details", "full-report");
    det.append(h("summary", null, p.t("res_report")));
    const body = h("div", "report-body");
    body.append(p.report);
    det.append(body);
    parts.push(det);
  }
  return parts;
}

/** A small score cell for the history table: number, band word and a bar. */
export function historyCell(score, band, labels) {
  const cell = document.createDocumentFragment();
  const line = h("span", "h-score");
  line.append(h("b", null, score ?? "–"));
  if (band) line.append(document.createTextNode(` ${band} ${labels.bands[band] ?? ""}`));
  cell.append(line);
  if (score != null) {
    const meter = h("span", "h-meter");
    const f = h("span", "h-fill");
    f.style.width = `${Math.min(100, Math.max(0, score))}%`;
    meter.append(f);
    cell.append(meter);
  }
  return cell;
}
