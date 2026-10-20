import { marked } from "https://cdn.jsdelivr.net/npm/marked@18.1.0/+esm";
import DOMPurify from "https://cdn.jsdelivr.net/npm/dompurify@3.4.16/+esm";
import { PROVIDERS, DEFAULT_PROVIDER, connect, describeError, keyOwner, pastedKey, sourcesMarkdown } from "./providers/index.js";
import { STRINGS } from "./i18n.js";
import { boot, call, refs, writeInput, forget } from "./py.js";
import * as P from "./prompts.js";
import { renderResult, historyCell } from "./render.js";

// ---------------------------------------------------------------- settings

const store = {
  get(k) { try { return sessionStorage.getItem(k) ?? localStorage.getItem(k); } catch { return null; } },
  set(k, v, remember) {
    try {
      sessionStorage.setItem(k, v);
      if (remember) localStorage.setItem(k, v); else localStorage.removeItem(k);
    } catch { /* storage blocked: keep in memory only */ }
  },
};
// key and model are kept per AI (mc.key.<id>, mc.model.<id>), so switching AI does not lose the others
const perAI = (fn) => Object.fromEntries(Object.keys(PROVIDERS).map((id) => [id, fn(id)]));
const savedAI = store.get("mc.provider");
const settings = {
  provider: Object.hasOwn(PROVIDERS, savedAI ?? "") ? savedAI : DEFAULT_PROVIDER,
  keys: perAI((id) => store.get(`mc.key.${id}`) || ""),
  remember: perAI((id) => { try { return !!localStorage.getItem(`mc.key.${id}`); } catch { return false; } }),
  models: perAI((id) => store.get(`mc.model.${id}`) || PROVIDERS[id].defaultModel),
  lang: store.get("mc.lang") || (navigator.language?.startsWith("ja") ? "ja" : "en"),
  org: store.get("mc.org") || "",
  get key() { return this.keys[this.provider]; },
  get model() { return this.models[this.provider]; },
};
/** Localized text; {ai} becomes the name of the AI `id` (the one in use by default). */
const t = (k, id = settings.provider) => {
  const s = STRINGS[settings.lang]?.[k] ?? STRINGS.en[k] ?? k;
  return typeof s === "string" ? s.replaceAll("{ai}", PROVIDERS[id].label) : s;
};
const $ = (sel) => document.querySelector(sel);

function applyLang() {
  document.documentElement.lang = settings.lang;
  document.querySelectorAll("[data-t]").forEach((el) => { el.textContent = t(el.dataset.t); });
}

function status(msg, isError = false) {
  const el = $("#status");
  el.textContent = msg || "";
  el.classList.toggle("error", isError);
}

// Model output can carry text planted in web pages or transcripts. Allow plain formatting and
// links only: no images (they would send data out), forms, styles, ids or classes.
const PURIFY = {
  ALLOWED_TAGS: ["p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "strong", "em", "b", "i", "code", "pre",
    "blockquote", "table", "thead", "tbody", "tr", "th", "td", "a", "del", "sup", "sub", "span"],
  ALLOWED_ATTR: ["href", "title", "colspan", "rowspan", "align"],
  ALLOWED_URI_REGEXP: /^https?:\/\//i,
};
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") { node.setAttribute("target", "_blank"); node.setAttribute("rel", "noopener noreferrer"); }
});
const safeHTML = (text) => DOMPurify.sanitize(marked.parse(text || ""), PURIFY);

function md(el, text) {
  el.innerHTML = safeHTML(text);
  el.hidden = false;
}

/**
 * The plan, then as links any page the search cited that the plan did not list itself (OpenAI's and
 * Anthropic's web search docs ask that cited sources be shown to the user). Parsed apart from the plan,
 * so an unclosed fence or comment in the reply cannot swallow the list.
 */
function showPlan(el, { text, sources }) {
  el.innerHTML = safeHTML(text) + safeHTML(sourcesMarkdown(text, sources, t("p_sources")));
  el.hidden = false;
}

/** Turn a {"error": ...} from the Python side into an exception with a readable message. */
function check(r) {
  if (r && typeof r === "object" && !Array.isArray(r) && r.error) throw new Error(`${t("e_py")} ${r.error}`);
  return r;
}

function client() {
  if (!settings.key) { status(t("need_key"), true); showTab("settings"); return null; }
  // the model is fixed with the AI for the whole run, so saving Settings mid-run cannot send one AI's model to another
  return { ...connect(settings.provider, settings.key), model: settings.model };
}

/** @param id the AI the run was started with, so an error names it even if Settings changed mid-run */
async function busy(button, fn, id = settings.provider) {
  button.disabled = true;
  try { await fn(); } catch (e) { console.error(e); status(`${t("err")}: ${describeError(e, (k) => t(k, id))}`, true); } finally { button.disabled = false; }
}

const config = () => JSON.parse(refs["config.default.json"]);
const today = () => new Date().toLocaleDateString("sv-SE"); // YYYY-MM-DD in the device's time zone

// ---------------------------------------------------------------- tabs

function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  document.querySelectorAll(".panel").forEach((p) => { p.hidden = p.id !== name; });
  // Settings shows the same notes next to the AI being chosen; two copies would only repeat each other
  $("#ai-banner").classList.toggle("off", name === "settings");
  if (name === "history") renderHistory();
}

// ---------------------------------------------------------------- prepare

const KINDS = {
  senior: { meeting_type: "one-on-one", my_position: "report", role: "senior" },
  report: { meeting_type: "one-on-one", my_position: "manager", role: "report" },
  candidate: { meeting_type: "one-on-one", my_position: "manager", role: "report" },
  peer: { meeting_type: "one-on-one", my_position: "peer", role: "peer" },
  external: { meeting_type: "external", my_position: null, role: "external" },
  meeting: { meeting_type: "meeting", my_position: null, role: "peer" },
};

async function runPrepare(e) {
  e.preventDefault();
  const c = client(); if (!c) return;
  const f = Object.fromEntries(new FormData(e.target));
  const kind = KINDS[f.kind];
  await busy(e.submitter, async () => {
    const history = await call("summary");
    const budget = config().research_budget;
    const answers = {
      person: { name: f.name, organisation: f.org },
      urls: f.urls.split(/\s+/).filter((u) => /^https?:\/\//.test(u)),
      kind: t(`kind_${f.kind}`), meeting_type: kind.meeting_type, my_position: kind.my_position,
      stage: kind.meeting_type === "external" ? f.stage : null,
      goal: f.goal, unsure: f.unsure || null, scheduled_minutes: Number(f.minutes) || null, date: f.date,
      language: settings.lang,
    };
    const user = [
      `P1 answers:\n${JSON.stringify(answers, null, 1)}`,
      f.profile ? `Profile pasted by the user:\n${f.profile}` : "",
      f.notes ? `Notes from an earlier meeting with this person (the user's own records; use, never store):\n${f.notes}` : "",
      `The user's history (learnings.py summary):\n${JSON.stringify(history, null, 1)}`,
      `Write the plan in ${settings.lang === "ja" ? "Japanese" : "English"}.`,
    ].filter(Boolean).join("\n\n");
    status(t("p_researching"));
    const plan = await c.ask({
      model: c.model,
      system: P.prepSystem(refs, settings.org, budget, c.provider.webSearch !== false),
      messages: [{ role: "user", content: user }],
      tools: c.prepTools(budget.person + (kind.meeting_type === "external" ? budget.company : 0)),
      effort: "high",
    });
    showPlan($("#prep-out"), plan);
    status(t("p_extracting"));
    const ex = await c.askJSON({
      model: c.model, system: P.prepExtractSystem, schema: P.prepSchema, effort: "low", maxTokens: 4000,
      messages: [{ role: "user", content: plan.text }],
    });
    const saved = await call("prep_save", [JSON.stringify({
      ...ex.data,
      meeting_type: kind.meeting_type, my_position: kind.my_position, stage: answers.stage,
      date: f.date, language: settings.lang, scheduled_minutes: answers.scheduled_minutes,
      counterpart_names: [f.name, ...f.name.split(/\s+/)].filter(Boolean), counterpart_role: kind.role,
    })], { persist: true });
    check(saved);
    const tokens = plan.usage.input + plan.usage.output + ex.usage.input + ex.usage.output;
    status(`${t("p_saved")} (${saved.id})  ${t("p_saved_hint")}  ${t("r_tokens")}: ${tokens.toLocaleString()}`);
  }, c.provider.id);
}

// ---------------------------------------------------------------- review

let current = null; // { transcript, plan }

async function runLoad(e) {
  e.preventDefault();
  const f = new FormData(e.target);
  const file = f.get("file");
  let bytes;
  if (file && file.size) bytes = new Uint8Array(await file.arrayBuffer());
  else if (f.get("paste").trim()) bytes = new TextEncoder().encode(f.get("paste"));
  else return;
  await busy(e.submitter, async () => {
    const path = writeInput(bytes);
    const tr = await call("parse", [path, ""]);
    forget(path);
    check(tr);
    current = { transcript: tr, plan: null };
    $("#review-out").hidden = true;
    showLoadInfo();
    if (!tr.has_speakers) {
      $("#assign-form").hidden = false;
      $("#intake-form").hidden = true;
    } else {
      $("#assign-form").hidden = true;
      await buildIntake();
    }
    status(t("r_found"));
  });
}

function showLoadInfo() {
  const tr = current.transcript;
  const mins = tr.duration_sec ? Math.round(tr.duration_sec / 60) : null;
  const el = $("#load-info");
  el.textContent = `${t("r_found")}: ${tr.utterances.length} / ${t("r_speakers")}: ${tr.speakers.join(", ") || t("r_none")}` +
    (mins ? ` / ${t("r_duration")}: ${mins} min` : "") + (tr.gaps?.length ? ` / ${t("r_gaps")}: ${tr.gaps.length}` : "");
  el.hidden = false;
}

async function runAssign(e) {
  e.preventDefault();
  const c = client(); if (!c) return;
  const names = new FormData(e.target).get("names").split(/[,、，]/).map((s) => s.trim()).filter(Boolean);
  await busy(e.submitter, async () => {
    status(t("r_assigning"));
    const messages = [{ role: "user", content: P.transcriptForModel(current.transcript) }];
    let out = null;
    for (let round = 0; round < 3; round++) {
      const r = await c.askJSON({
        model: c.model, system: P.speakerSystem(names), schema: P.speakerSchema(names), effort: "medium", maxTokens: 8000, messages,
      });
      const spec = {
        ranges: (r.data.ranges ?? []).filter((x) => names.includes(x.speaker)).map((x) => [x.from, x.to, x.speaker]),
        drop: (r.data.drop ?? []).map((x) => [x.from, x.to, x.reason]),
      };
      out = check(await call("assign", [JSON.stringify(current.transcript), JSON.stringify(spec)]));
      if (!out.errors) break;
      messages.push({ role: "assistant", content: JSON.stringify(r.data) });
      messages.push({ role: "user", content: `Fix these problems and return the whole corrected JSON:\n${out.errors.join("\n")}` });
    }
    if (out.errors) throw new Error(`${t("e_assign")} ${out.errors.join("; ")}`);
    current.transcript = out;
    $("#assign-form").hidden = true;
    showLoadInfo();
    await buildIntake();
    status(t("r_found"));
  }, c.provider.id);
}

function field(labelKey, control) {
  const label = document.createElement("label");
  const span = document.createElement("span");
  span.textContent = t(labelKey);
  label.append(span, control);
  return label;
}
function select(name, options, value) {
  const s = document.createElement("select");
  s.name = name;
  for (const [v, labelKey, raw] of options) {
    const o = document.createElement("option");
    o.value = v; o.textContent = raw ?? t(labelKey);
    if (v === value) o.selected = true;
    s.append(o);
  }
  return s;
}
function input(name, value = "", type = "text") {
  const i = document.createElement("input");
  i.name = name; i.type = type; i.value = value ?? "";
  return i;
}

async function refreshPlan(date) {
  const plan = check(await call("prep_find", [date]));
  current.plan = plan;
  const box = $("#plan-box");
  box.replaceChildren();
  if (plan) {
    const cb = input("use_plan", "", "checkbox"); cb.checked = true;
    const span = document.createElement("span");
    span.textContent = `${t("r_plan")}: ${plan.id} — ${plan.goal}  (${t("r_use_plan")})`;
    box.append(cb, span);
  }
  box.hidden = !plan;
  return plan;
}

async function buildIntake() {
  const tr = current.transcript;
  const date = (tr.started_at || "").slice(0, 10) || today();
  const form = $("#intake-form");
  form.replaceChildren();
  const planBox = document.createElement("label");
  planBox.className = "check"; planBox.id = "plan-box";
  form.append(planBox);
  const plan = await refreshPlan(date);
  const row1 = document.createElement("div"); row1.className = "row";
  row1.append(
    field("r_type", select("meeting_type", [["one-on-one", "type_one"], ["meeting", "type_meeting"], ["external", "type_external"]], plan?.meeting_type || "one-on-one")),
    field("r_position", select("my_position", [["report", "pos_report"], ["manager", "pos_manager"], ["peer", "pos_peer"]], plan?.my_position || "report")),
    field("p_date", input("date", date, "date")),
  );
  const row2 = document.createElement("div"); row2.className = "row";
  row2.append(
    field("r_me", select("me", tr.speakers.map((s) => [s, null, s]), tr.speakers[0])),
    field("r_fac", select("facilitator", [["", "fac_none"], ["me", "fac_me"], ...tr.speakers.map((s) => [s, null, s])], "")),
  );
  const row3 = document.createElement("div"); row3.className = "row";
  row3.append(
    field("r_scheduled", input("scheduled", plan?.scheduled_minutes ?? "", "number")),
    field("r_actual", input("actual", "", "number")),
  );
  form.append(row1, row2, row3, field("r_goal", input("goal", plan?.goal ?? "")));
  const rels = document.createElement("fieldset");
  rels.className = "form";
  for (const s of tr.speakers) {
    const row = document.createElement("div"); row.className = "row"; row.dataset.speaker = s;
    const lab = field("r_rel", select(`rel:${s}`, [["senior", "rel_senior"], ["manager", "rel_manager"], ["peer", "rel_peer"], ["report", "rel_report"], ["external", "rel_external"]], "peer"));
    lab.querySelector("span").textContent = `${s} — ${t("r_rel")}`;
    row.append(lab, field("r_alias", input(`alias:${s}`)));
    rels.append(row);
  }
  form.append(rels);
  const quiet = document.createElement("label"); quiet.className = "check";
  const qcb = input("reserved", "", "checkbox");
  const qs = document.createElement("span"); qs.textContent = t("r_reserved");
  quiet.append(qcb, qs);
  const run = document.createElement("button"); run.type = "submit"; run.className = "primary"; run.textContent = t("r_run");
  form.append(quiet, run);
  // no relationship to ask for the speaker who is the user
  const meSelect = form.elements.me;
  const syncMe = () => rels.querySelectorAll(".row").forEach((r) => { r.hidden = r.dataset.speaker === meSelect.value; });
  meSelect.addEventListener("change", syncMe);
  syncMe();
  form.elements.date.addEventListener("change", (ev) => refreshPlan(ev.target.value));
  form.hidden = false;
}

function rubricKey(meta) {
  return meta.meeting_type === "one-on-one" ? `one-on-one/${meta.my_position || "peer"}` : meta.meeting_type;
}

async function runReview(e) {
  e.preventDefault();
  const c = client(); if (!c) return;
  const f = new FormData(e.target);
  const tr = current.transcript;
  const usePlan = current.plan && f.get("use_plan") === "on";
  const me = f.get("me");
  const relationships = {}, aliases = {};
  for (const s of tr.speakers) {
    if (s === me) continue;
    relationships[s] = f.get(`rel:${s}`);
    const a = (f.get(`alias:${s}`) || "").split(/[,、，]/).map((x) => x.trim()).filter(Boolean);
    if (a.length) aliases[s] = a;
  }
  const meta = {
    meeting_type: f.get("meeting_type"),
    my_position: f.get("meeting_type") === "one-on-one" ? f.get("my_position") : null,
    me, facilitator: f.get("facilitator") || null, relationships, aliases,
    scheduled_minutes: Number(f.get("scheduled")) || null, actual_minutes: Number(f.get("actual")) || null,
    date: f.get("date"), goal: f.get("goal") || null, stage: usePlan ? current.plan.stage : null,
    counterpart_reserved: f.get("reserved") === "on", language: settings.lang, prep_id: usePlan ? current.plan.id : null,
  };
  await busy(e.submitter, async () => {
    const metrics = check(await call("measure", [JSON.stringify(tr), JSON.stringify(meta)]));
    const key = rubricKey(meta);
    const rubric = config().rubrics[key];
    const ids = [...Object.keys(rubric.meeting), ...Object.keys(rubric.self)];
    const openActions = (await call("summary")).open_actions;
    const system = P.judgeSystem(refs, meta, key, rubric);
    const schema = P.judgementSchema(ids);
    const usage = { input: 0, output: 0 };
    const add = (u) => { usage.input += u.input; usage.output += u.output; };

    status(t("r_judging"));
    const messages = [{ role: "user", content: P.judgeUser(tr, meta, metrics, openActions, usePlan ? current.plan : null) }];
    let r = await c.askJSON({ model: c.model, system, schema, messages, effort: "high", maxTokens: 16000 });
    add(r.usage);
    let judgement = P.normaliseJudgement(r.data, ids);

    status(t("r_verifying"));
    let verdict = check(await call("verify", [JSON.stringify(judgement), JSON.stringify(tr)]));
    for (let round = 0; round < 2 && !verdict.ok; round++) {
      status(t("r_retry"));
      messages.push({ role: "assistant", content: JSON.stringify(r.data) });
      messages.push({ role: "user", content: `These evidence items failed verification. Fix each one (copy quotes verbatim from the cited utterance, fix indices) and return the whole corrected JSON:\n${verdict.failures.join("\n")}` });
      r = await c.askJSON({ model: c.model, system, schema, messages, effort: "high", maxTokens: 16000 });
      add(r.usage);
      judgement = P.normaliseJudgement(r.data, ids);
      verdict = check(await call("verify", [JSON.stringify(judgement), JSON.stringify(tr)]));
    }
    if (!verdict.ok) judgement = P.dropFailures(judgement, verdict.failures);

    status(t("r_scoring"));
    const scored = check(await call("score", [JSON.stringify(judgement), JSON.stringify(meta), JSON.stringify(metrics)]));
    if (scored.errors) throw new Error(`${t("e_judgement")} ${scored.errors.join("; ")}`);

    status(t("r_writing"));
    const report = await c.ask({
      model: c.model, system: P.reportSystem(refs, settings.lang), effort: "medium", maxTokens: 8000,
      messages: [{ role: "user", content: P.reportUser(meta, scored.markdown, judgement, metrics, tr) }],
    });
    add(report.usage);
    // save first, so a rendering error cannot lose a paid result
    check(await call("save", [JSON.stringify(judgement), JSON.stringify(scored.result), JSON.stringify(tr), JSON.stringify(meta)], { persist: true }));
    try { renderReview(scored.result, report.text, judgement, tr, meta.me); }
    catch (e) { console.error(e); status(`${t("r_saved")}  ${t("err")}: ${describeError(e, t)}`, true); return; }
    status(`${t("r_saved")}  ${t("r_tokens")}: ${(usage.input + usage.output).toLocaleString()}`);
  }, c.provider.id);
}

const labelsFor = () => JSON.parse(refs[`scripts/locales/${settings.lang}.json`]).labels;

function renderReview(result, reportText, judgement, transcript, me) {
  const out = $("#review-out");
  const report = document.createElement("div");
  report.innerHTML = safeHTML(reportText);
  out.replaceChildren(...renderResult({
    result, judgement, transcript, me, report,
    labels: labelsFor(), t, bands: config().bands, lang: settings.lang,
  }));
  out.hidden = false;
  out.scrollIntoView({ block: "start" });
}

// ---------------------------------------------------------------- history

async function renderHistory() {
  const rows = await call("history");
  const tableBox = $("#score-table");
  if (!rows.length) { tableBox.textContent = t("h_empty"); } else {
    const labels = labelsFor();
    const table = document.createElement("table"); table.className = "scores";
    const head = document.createElement("tr");
    for (const k of ["h_date", "h_kind", "h_meeting", "h_self"]) { const th = document.createElement("th"); th.textContent = t(k); head.append(th); }
    table.append(head);
    for (const r of rows.slice().reverse()) {
      const tr = document.createElement("tr");
      for (const v of [r.date, r.rubric]) { const td = document.createElement("td"); td.textContent = v; tr.append(td); }
      for (const [sc, band] of [[r.meeting_score, r.meeting_band], [r.self_score, r.self_band]]) {
        const td = document.createElement("td"); td.append(historyCell(sc, band, labels)); tr.append(td);
      }
      table.append(tr);
    }
    tableBox.replaceChildren(table);
  }
  const text = await call("learnings_md", [], { json: false });
  if (text) md($("#learn-md"), text.replace(/^<!--.*-->\n/, "")); else $("#learn-md").textContent = t("h_empty");
}

async function exportBlock(e) {
  await busy(e.target, async () => {
    const block = await call("export_block", [settings.lang], { json: false });
    await navigator.clipboard.writeText(block);
    status(t("copied"));
  });
}

async function importBlock(e) {
  e.preventDefault();
  const text = new FormData(e.target).get("block");
  if (!text.trim()) return;
  if (!text.includes("<!-- meeting-coach learnings v1 -->")) { status(t("e_block"), true); return; }
  if (!confirm(t("h_import_confirm"))) return;
  await busy(e.submitter, async () => {
    const r = check(await call("import_block", [text, settings.lang], { persist: true }));
    status(`${t("imported")}: ${r.actions} / ${r.habits} / ${r.plans}`);
    renderHistory();
  });
}

async function downloadBackup(e) {
  await busy(e.target, async () => {
    const data = await call("backup", [], { json: false });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([data], { type: "application/json" }));
    a.download = `meeting-coach-backup-${today()}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  });
}

async function restoreBackup(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  try {
    const data = await file.text();
    const info = check(await call("backup_info", [data]));
    if (!confirm(t("h_restore_confirm").replace("{n}", info.files).replace("{r}", info.reviews).replace("{p}", info.plans))) { e.target.value = ""; return; }
    const r = check(await call("restore", [data], { persist: true }));
    status(`${t("imported")}: ${r.restored}`);
    renderHistory();
  } catch (err) { status(`${t("err")}: ${describeError(err, t)}`, true); }
  e.target.value = "";
}

async function wipe(e) {
  if (!confirm(t("h_wipe_confirm"))) return;
  await busy(e.target, async () => {
    const r = check(await call("wipe", [], { persist: true }));
    for (const s of [localStorage, sessionStorage]) {
      try { Object.keys(s).filter((k) => k.startsWith("mc.")).forEach((k) => s.removeItem(k)); } catch { /* storage blocked */ }
    }
    // back to what a fresh page would load, so the form shows nothing that is no longer stored
    for (const id of Object.keys(PROVIDERS)) {
      settings.keys[id] = "";
      settings.remember[id] = false;
      settings.models[id] = PROVIDERS[id].defaultModel;
    }
    Object.assign(settings, { provider: DEFAULT_PROVIDER, org: "" });
    fillSettings();
    status(t("h_wiped").replace("{n}", r.deleted));
    renderHistory();
  });
}

// ---------------------------------------------------------------- settings form

const OTHER_MODEL = "__other";
const ISSUES = "https://github.com/ry071702-prog/meeting-coach/issues";
const option = (value, text) => Object.assign(document.createElement("option"), { value, textContent: text });

function link(text, href) {
  return Object.assign(document.createElement("a"), { textContent: text, href, target: "_blank", rel: "noopener noreferrer" });
}

// a provider whose status is "tested" gets no note
const STATUS_NOTES = { untested: { label: "ai_untested", text: "ai_unverified" }, experimental: { label: "ai_experimental", text: "ai_varies" } };

/** The cautions that go with an AI: Gemini's free tier, and how far it has been tested against the real API. */
function aiNotes(el, id) {
  const note = (kind, label, text, a) => {
    const p = document.createElement("p");
    p.className = `ai-note ${kind}`;
    p.append(Object.assign(document.createElement("strong"), { textContent: label }), a ? `${text}  ` : text, ...(a ? [a] : []));
    return p;
  };
  const notes = [];
  if (id === "gemini") notes.push(note("warn", t("ai_caution"), t("gemini_free"), link(t("gemini_terms"), "https://ai.google.dev/gemini-api/terms")));
  if (PROVIDERS[id].webSearch === false) notes.push(note("", t("ai_prep"), t(`${id}_urls`)));
  const status = STATUS_NOTES[PROVIDERS[id].status];
  if (status) notes.push(note("", t(status.label), t(status.text, id), link(t("ai_issues"), ISSUES)));
  el.replaceChildren(...notes);
  el.hidden = !notes.length;
}

/** Show one AI's key, model and cautions in the form, without saving anything. */
function fillAI(id) {
  const f = $("#settings-form").elements;
  const p = PROVIDERS[id];
  $("#s-key-label").textContent = t("s_key", id);
  f.key.value = settings.keys[id];
  f.key.placeholder = p.keyPlaceholder;
  $("#key-link").href = p.keyUrl;
  f.remember.checked = settings.remember[id];
  const model = settings.models[id];
  const listed = p.models.some((m) => m.id === model);
  f.model.replaceChildren(...p.models.map((m) => option(m.id, m.label)), option(OTHER_MODEL, t("s_model_other")));
  f.model.value = listed ? model : OTHER_MODEL;
  f.model_custom.value = listed ? "" : model;
  f.model_custom.closest("label").hidden = listed;
  aiNotes($("#s-notes"), id);
}

function fillSettings() {
  const f = $("#settings-form").elements; // .elements: a field named "lang" would clash with form.lang
  f.provider.replaceChildren(...Object.values(PROVIDERS).map((p) => option(p.id, p.label)));
  f.provider.value = settings.provider;
  fillAI(settings.provider);
  f.lang.value = settings.lang;
  f.org.value = settings.org;
  aiNotes($("#ai-banner"), settings.provider);
}

function saveSettings(e) {
  e.preventDefault();
  const f = e.target.elements;
  const id = f.provider.value;
  const model = f.model.value === OTHER_MODEL ? f.model_custom.value.trim() : f.model.value;
  if (!model) { status(t("s_model_empty"), true); f.model_custom.focus(); return; }
  // a key that plainly belongs to another AI would be sent to the wrong company
  const key = pastedKey(f.key.value);
  const owner = keyOwner(key);
  if (owner && owner !== id) { status(t("s_key_other", id).replaceAll("{other}", PROVIDERS[owner].label), true); f.key.focus(); return; }
  settings.provider = id;
  settings.keys[id] = key;
  settings.remember[id] = f.remember.checked;
  settings.models[id] = model;
  Object.assign(settings, { lang: f.lang.value, org: f.org.value });
  store.set("mc.provider", id, true);
  store.set(`mc.key.${id}`, settings.keys[id], settings.remember[id]);
  store.set(`mc.model.${id}`, settings.models[id], true);
  store.set("mc.lang", settings.lang, true);
  store.set("mc.org", settings.org, true);
  applyLang();
  fillSettings();
  status(t("s_saved"));
}

// ---------------------------------------------------------------- start

async function main() {
  applyLang();
  fillSettings();
  $("#prep-form").elements.date.value = today();
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  $("#prep-form").elements.kind.addEventListener("change", (e) => { document.querySelector(".stage-field").hidden = e.target.value !== "external"; });
  $("#settings-form").addEventListener("submit", saveSettings);
  $("#settings-form").elements.provider.addEventListener("change", (e) => fillAI(e.target.value));
  $("#settings-form").elements.model.addEventListener("change", (e) => {
    const f = e.target.form.elements;
    f.model_custom.closest("label").hidden = e.target.value !== OTHER_MODEL;
    if (e.target.value === OTHER_MODEL) f.model_custom.focus();
  });
  document.querySelectorAll("#prepare button, #review button, #history button").forEach((b) => { b.disabled = true; });
  try {
    await boot((step) => status(t(`boot_${step}`)));
  } catch (e) {
    status(`${t("err")}: ${describeError(e, t)}`, true);
    return;
  }
  document.querySelectorAll("#prepare button, #review button, #history button").forEach((b) => { b.disabled = false; });
  $("#prep-form").addEventListener("submit", runPrepare);
  $("#load-form").addEventListener("submit", runLoad);
  $("#assign-form").addEventListener("submit", runAssign);
  $("#intake-form").addEventListener("submit", runReview);
  $("#import-form").addEventListener("submit", importBlock);
  $("#export").addEventListener("click", exportBlock);
  $("#backup").addEventListener("click", downloadBackup);
  $("#restore").addEventListener("change", restoreBackup);
  $("#wipe").addEventListener("click", wipe);
  status(settings.key ? t("boot_done") : t("need_key"));
}

main();
