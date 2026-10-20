// AI の API のモック (Anthropic・OpenAI・Gemini)  リクエストを共通の形にそろえて呼び出しの種類を見分け、
// その会社の応答の形で返す  応答の形は各社の API リファレンスの例と、Gemini は本物の応答 (2026-10-15) に合わせた
import fs from "node:fs";
import path from "node:path";

const HERE = path.dirname(new URL(import.meta.url).pathname);
const SAMPLE = JSON.parse(fs.readFileSync(path.join(HERE, "fixtures/judgement.json"), "utf8"));

const norm = (s) => String(s).normalize("NFKC").toLowerCase().replace(/[\s\p{P}\p{S}]/gu, "");

/** モデルに渡された文字起こし行 "[i] ~00:00 話者: 本文" を読む */
function transcriptLines(text) {
  const out = [];
  for (const line of text.split("\n")) {
    const m = line.match(/^\[(\d+)\](?: ~?\d+:\d\d)? (.+?): (.*)$/);
    if (m) out.push({ i: Number(m[1]), speaker: m[2], text: m[3] });
  }
  return out;
}

function between(text, a, b) {
  const s = text.indexOf(a);
  if (s < 0) return null;
  const e = b ? text.indexOf(b, s + a.length) : -1;
  return text.slice(s + a.length, e < 0 ? undefined : e);
}

/** 引用が入っている発言を探して i を付け直す  見つからなければ null */
function relocate(ev, lines) {
  if (ev == null || ev.quote == null) {
    if (ev && Array.isArray(ev.range)) {
      const max = lines.length - 1;
      return { ...ev, range: [Math.min(ev.range[0], max), Math.min(ev.range[1], max)] };
    }
    return ev;
  }
  const q = norm(ev.quote);
  const hit = lines.find((l) => norm(l.text).includes(q));
  return hit ? { ...ev, i: hit.i } : null;
}

/** 発言の途中から引用を切り出す (逐語なので verify_evidence を通る) */
function quoteFrom(line, lang) {
  const body = line.text.replace(/^\S+[、,]\s/, ""); // 先頭の相槌を外す
  if (lang === "ja") {
    const s = Math.max(0, Math.floor(body.length / 3));
    return body.slice(s, s + 12);
  }
  const w = body.split(/\s+/);
  const s = Math.floor(w.length / 3);
  return w.slice(s, s + 5).join(" ");
}

/** 各社のリクエストを {system, messages: [{role, content}], schema, search} にそろえる */
export function normalize(provider, body) {
  if (provider === "openai") {
    return {
      system: body.instructions ?? "", messages: body.input ?? [],
      schema: body.text?.format?.schema, search: !!body.tools?.some((t) => t.type === "web_search"),
    };
  }
  if (provider === "gemini") {
    return {
      system: (body.systemInstruction?.parts ?? []).map((p) => p.text).join(""),
      messages: (body.contents ?? []).map((c) => ({ role: c.role, content: c.parts.map((p) => p.text).join("") })),
      schema: body.generationConfig?.responseJsonSchema, search: !!body.tools?.some((t) => t.googleSearch || t.urlContext),
    };
  }
  return {
    system: Array.isArray(body.system) ? body.system.map((b) => b.text).join("") : body.system ?? "",
    messages: body.messages ?? [],
    schema: body.output_config?.format?.schema, search: !!body.tools?.some((t) => String(t.type).startsWith("web_search")),
  };
}

function judgeResponse(body) {
  const user = body.messages[0].content;
  const system = body.system;
  const lines = transcriptLines(user);
  const meta = JSON.parse(between(user, "meta.json:\n", "\n\nmetrics.json:"));
  const lang = meta.language;
  const rubric = JSON.parse(between(system, "Criteria and weights:\n", "\nJudge every criterion"));
  const trackOf = (id) => (id in rubric.meeting ? "meeting" : "self");
  const ids = [...Object.keys(rubric.meeting), ...Object.keys(rubric.self)];
  const mine = lines.filter((l) => l.speaker === meta.me && norm(l.text).length >= 15);
  const pick = (k) => mine[k % mine.length];
  const synthEv = (k) => { const l = pick(k); return { i: l.i, quote: quoteFrom(l, lang), absence: null, range: null }; };
  const sampleBy = Object.fromEntries(SAMPLE.criteria.map((c) => [c.id, c]));

  const criteria = ids.map((id, k) => {
    const c = sampleBy[id];
    if (c) {
      const ev = c.evidence.map((e) => relocate(e, lines));
      if (ev.every(Boolean)) return { ...c, track: trackOf(id), evidence: ev };
    }
    return {
      id, track: trackOf(id), level: 1 + (k % 3), evidence: [synthEv(k)],
      reason: lang === "ja" ? "モックの判定 (E2E 用)" : "Mock judgement for the E2E run",
    };
  });
  const keep = (list) => list.map((x) => {
    const ev = (x.evidence || []).map((e) => relocate(e, lines));
    return ev.every(Boolean) ? { ...x, evidence: ev } : null;
  }).filter(Boolean);
  const signals = SAMPLE.signals.map((s) => (s.quote != null ? relocate(s, lines) : s)).filter(Boolean);
  let strengths = keep(SAMPLE.strengths);
  let improvements = keep(SAMPLE.improvements);
  let nextActions = SAMPLE.next_actions;
  if (!strengths.length) strengths = [{ text: lang === "ja" ? "結論から話していた" : "Opened with the decision needed", evidence: [synthEv(0)] }];
  if (!improvements.length) {
    improvements = [{
      criterion: ids[ids.length - 1], what_happened: lang === "ja" ? "質問を重ねた" : "Stacked several questions",
      evidence: [synthEv(1)], try_instead: lang === "ja" ? "質問は1つずつ" : "Ask one question at a time",
    }];
  }
  if (lang !== "ja") {
    nextActions = [{ text: "Ask one question at a time and wait" }, { text: "Name an owner and a date before closing" }];
  }
  return {
    criteria, signals: lang === "ja" ? signals : [], strengths, improvements, next_actions: nextActions,
    habits: [], worked: SAMPLE.worked || [], previous_actions_check: [], plan_check: [],
  };
}

/** 話者なしの文字起こしに、元の話者つきファイルから話者を当てる */
function assignResponse(body, labelled) {
  const lines = transcriptLines(body.messages[0].content);
  const src = labelled.split("\n").map((l) => l.match(/^(?:\[[\d:]+\] )?([^:\s]+): (.*)$/)).filter(Boolean)
    .map((m) => ({ speaker: m[1], n: norm(m[2]) }));
  const ranges = [];
  for (const l of lines) {
    const hit = src.find((s) => s.n.includes(norm(l.text)));
    const speaker = hit ? hit.speaker : src[0].speaker;
    const last = ranges[ranges.length - 1];
    if (last && last.speaker === speaker && last.to === l.i - 1) last.to = l.i;
    else ranges.push({ from: l.i, to: l.i, speaker });
  }
  return { ranges, drop: [] };
}

function reportResponse(body) {
  const user = body.messages[0].content;
  const ja = /Japanese/.test(body.system);
  const table = between(user, "Score table (paste as is):\n", "\n\njudgement.json:") || "";
  return ja
    ? `## 会議の振り返り (モック)\n\n${table}\n\n### よかった点\n- 結論から入っていた\n\n### 次に試すこと\n1. 説明の前に相手の課題を1つ聞く\n`
    : `## Post-meeting report (mock)\n\n${table}\n\n### What went well\n- Opened with the decision\n\n### Try next\n1. Ask one question at a time\n`;
}

const PREP_JA = "## 準備メモ (モック)\n\n| # | 質問 | ねらい |\n|---|---|---|\n| 1 | いま一番手間なのは何ですか | 課題を知る |\n| 2 | いつまでに決めたいですか | 期日を知る |\n\n### 出典\n1. モックの会社ページ — https://example.com/mock-company\n";
const PREP_EN = "## Meeting plan (mock)\n\n| # | Question | Aim |\n|---|---|---|\n| 1 | What takes the most time today? | Learn the pain |\n| 2 | When do you need to decide? | Learn the deadline |\n\n### Sources\n1. Mock company page — https://example.com/mock-company\n\n```\n";
// en ends in a fence it never closes, as a model's reply can: the pages the app adds after it must still be links

/** 1回の呼び出し (normalize 済み) を分類する */
export function classify(body) {
  const { schema } = body;
  if (body.search) return "prep_plan";
  if (schema?.properties?.intents) return "prep_extract";
  if (schema?.properties?.ranges) return "assign";
  if (schema?.properties?.criteria) return "judge";
  if (/post-meeting report/.test(body.system)) return "report";
  return "unknown";
}

/** 準備の検索で読んだことにするページ  題名の崩れた括弧と改行は、リンクの書き方を壊さないかを見るため */
export const CITED = { url: "https://example.com/mock-profile", title: "Mock profile ](x) [example\n\n# not a heading" };
/** 計画文が自分で出典に挙げたページ  検索の注釈にも入るが、画面で2回目は出さない */
export const LISTED = { url: "https://example.com/mock-company?utm_source=openai", title: "Mock company page" };

/** 本文テキストを、その会社の応答の形に包む  cites はその会社の形の出典の注釈にする (Gemini は URL を読むだけなので無し) */
function wrap(provider, text, model, cites = []) {
  if (provider === "openai") {
    return {
      id: `resp_mock_${Math.random().toString(36).slice(2, 10)}`, object: "response", status: "completed", model,
      output: [
        { type: "reasoning", id: "rs_mock", summary: [] },
        { type: "message", id: "msg_mock", role: "assistant", status: "completed", content: [{ type: "output_text", text, annotations: cites.map((c) => ({ type: "url_citation", start_index: 0, end_index: 8, ...c })) }] },
      ],
      usage: { input_tokens: 1200, output_tokens: 300 },
    };
  }
  if (provider === "gemini") {
    return {
      candidates: [{ content: { role: "model", parts: [{ text: "thinking (mock)", thought: true }, { text }] }, finishReason: "STOP" }],
      usageMetadata: { promptTokenCount: 1200, candidatesTokenCount: 200, thoughtsTokenCount: 100 },
    };
  }
  return {
    id: `msg_mock_${Math.random().toString(36).slice(2, 10)}`, type: "message", role: "assistant", model,
    content: [{ type: "text", text, ...(cites.length ? { citations: cites.map((c) => ({ type: "web_search_result_location", cited_text: "mock", encrypted_index: "mock", ...c })) } : {}) }],
    stop_reason: "end_turn", stop_sequence: null,
    usage: { input_tokens: 1200, output_tokens: 300 },
  };
}

/** @param provider "anthropic" | "openai" | "gemini"  @param raw その会社の形のリクエスト本文 */
export function respond(provider, raw, { labelled = "" } = {}) {
  const body = normalize(provider, raw);
  const kind = classify(body);
  const ja = /[぀-ヿ]/.test(JSON.stringify(body.messages));
  let text;
  if (kind === "judge") text = JSON.stringify(judgeResponse(body));
  else if (kind === "assign") text = JSON.stringify(assignResponse(body, labelled));
  else if (kind === "report") text = reportResponse(body);
  else if (kind === "prep_plan") text = ja ? PREP_JA : PREP_EN;
  else if (kind === "prep_extract") {
    text = JSON.stringify({
      meeting_type: "one-on-one", my_position: "report", stage: null,
      goal: ja ? "予算の判断をもらう" : "Get a budget decision",
      intents: ja ? ["課題を知る", "期日を知る"] : ["Learn the pain", "Learn the deadline"], focus_action_ids: [],
    });
  } else text = "{}";
  return { kind, message: wrap(provider, text, raw.model, kind === "prep_plan" ? [CITED, LISTED, CITED] : []) };
}
