// Claude (Anthropic), straight from the browser with the user's own key.
// Nothing passes through any server other than Anthropic's.
import Anthropic from "https://cdn.jsdelivr.net/npm/@anthropic-ai/sdk@0.132.1/+esm";
import { RefusalError, citedSources, makeAskJSON, nonEmpty } from "./common.js";

export const id = "anthropic";
export const label = "Claude";
export const keyPlaceholder = "sk-ant-...";
export const keyPattern = /^sk-ant-/; // how this company's keys start, to catch a key pasted under the wrong AI
export const keyUrl = "https://platform.claude.com/settings/keys";
export const status = "untested"; // run only against a mock so far, never the real API
export const models = [
  { id: "claude-opus-5-5", label: "Claude Opus 5.5" },
  { id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5" },
];
export const defaultModel = models[0].id;

export function makeClient(apiKey) {
  // dangerouslyAllowBrowser: the key is the user's own and stays in their browser (BYOK)
  return new Anthropic({ apiKey, dangerouslyAllowBrowser: true });
}

const FALLBACK_BETA = "server-side-fallback-2026-07-01";

/**
 * One request, with the server-side refusal fallback, pause_turn resumption and usage totals.
 * @returns {Promise<{message: object, text: string, usage: {input: number, output: number}, sources: {url: string, title: string}[]}>}
 */
export async function ask(client, { model, system, messages, tools, schema, effort = "high", maxTokens = 16000 }) {
  const base = {
    model,
    max_tokens: maxTokens,
    system,
    output_config: { effort, ...(schema ? { format: { type: "json_schema", schema } } : {}) },
    ...(tools ? { tools } : {}),
  };
  const usage = { input: 0, output: 0 };
  let convo = [...messages];
  let useFallback = true;
  let paused = []; // text written before a pause_turn; the continued reply carries on after it
  for (let turn = 0; turn < 8; turn++) {
    let resp;
    try {
      resp = useFallback
        ? await client.beta.messages.create({ ...base, messages: convo, betas: [FALLBACK_BETA], fallbacks: "default" })
        : await client.messages.create({ ...base, messages: convo });
    } catch (e) {
      // an account or model without the fallback beta: retry once without it
      if (useFallback && e?.status === 400 && /fallback/i.test(String(e?.message))) {
        useFallback = false;
        turn--;
        continue;
      }
      throw e;
    }
    usage.input += resp.usage?.input_tokens ?? 0;
    usage.output += resp.usage?.output_tokens ?? 0;
    if (resp.stop_reason === "refusal") {
      throw new RefusalError(resp.stop_details?.explanation || "The request was declined.");
    }
    if (resp.stop_reason === "max_tokens" && base.max_tokens < 32000) {
      // cut off mid-answer: retry once with twice the room instead of returning a broken result
      base.max_tokens = Math.min(base.max_tokens * 2, 32000);
      convo = [...messages];
      paused = [];
      continue;
    }
    if (resp.stop_reason === "max_tokens") throw new Error("The answer was too long and got cut off.");
    if (resp.stop_reason === "pause_turn") {
      // long server-tool turn: send the partial turn back so the model continues
      convo = [...convo, { role: "assistant", content: resp.content }];
      paused.push(...resp.content.filter((b) => b.type === "text"));
      continue;
    }
    const texts = [...paused, ...resp.content.filter((b) => b.type === "text")];
    const text = texts.map((b) => b.text).join("");
    // the pages search results were cited from; web_fetch citations have no URL and drop out
    const sources = citedSources(texts.flatMap((b) => b.citations ?? []));
    return nonEmpty({ message: resp, text, usage, sources });
  }
  throw new Error("The model kept pausing; try again.");
}

/** JSON that matches `schema`; falls back to JSON in plain text if the API refuses the schema. */
export const askJSON = makeAskJSON(ask, (e) => e?.status === 400 && /schema|output_config|format/i.test(String(e?.message)));

/** Server-side tools for the prepare step: up to `searches` web searches, plus page fetches. */
export function prepTools(searches) {
  return [
    { type: "web_search_20260209", name: "web_search", max_uses: searches },
    { type: "web_fetch_20260209", name: "web_fetch", max_uses: 10 },
  ];
}
