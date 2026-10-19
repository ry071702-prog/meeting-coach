// OpenAI, called with fetch straight from the browser with the user's own key (Responses API).
// Nothing passes through any server other than OpenAI's.
import { ApiError, RefusalError, makeAskJSON, nonEmpty } from "./common.js";

export const id = "openai";
export const label = "OpenAI";
export const keyPlaceholder = "sk-...";
export const keyUrl = "https://platform.openai.com/api-keys";
export const status = "untested"; // written from the API reference; never run against the real API
export const models = [
  { id: "gpt-6-astra", label: "GPT-6 Astra" },
  { id: "gpt-6.1-sol", label: "GPT-6.1 Sol" },
  { id: "gpt-6-luna", label: "GPT-6 Luna" },
];
export const defaultModel = models[0].id;

const ENDPOINT = "https://api.openai.com/v1/responses";

/** @param {{fetch?: typeof fetch}} [opts] a fetch to use instead of the browser's (tests) */
export function makeClient(apiKey, { fetch: f } = {}) {
  return { apiKey, fetch: f ?? ((...a) => fetch(...a)) };
}

async function post(client, body) {
  const res = await client.fetch(ENDPOINT, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${client.apiKey}` },
    body: JSON.stringify(body),
  });
  const j = await res.json().catch(() => null);
  if (!res.ok) {
    const err = j?.error ?? {};
    throw Object.assign(new ApiError(res.status, err.message || `HTTP ${res.status}`), { code: err.code, type: err.type, param: err.param });
  }
  return j;
}

/**
 * One request. `maxTokens` is not sent: reasoning shares the output cap, the reference advises leaving
 * at least 25,000 tokens for it, and a fixed number would be rejected by a typed-in model with a lower cap.
 * @returns {Promise<{message: object, text: string, usage: {input: number, output: number}}>}
 */
export async function ask(client, { model, system, messages, tools, schema, effort = "high" }) {
  const resp = await post(client, {
    model,
    store: false, // the default keeps every response for at least 30 days; meetings should not be kept
    ...(system ? { instructions: system } : {}),
    input: messages.map((m) => ({ role: m.role, content: m.content })),
    reasoning: { effort }, // low, medium and high pass on all three models above
    ...(schema ? { text: { format: { type: "json_schema", name: "answer", strict: true, schema } } } : {}),
    ...(tools ? { tools } : {}),
  });
  const usage = { input: resp.usage?.input_tokens ?? 0, output: resp.usage?.output_tokens ?? 0 };
  if (resp.status === "incomplete") {
    const why = resp.incomplete_details?.reason;
    if (why === "content_filter") throw new RefusalError(`(${why})`);
    if (why === "max_output_tokens") throw new Error("The answer was too long and got cut off.");
    throw new Error(`The model stopped early (${why ?? "incomplete"}).`);
  }
  if (resp.status !== "completed") throw new Error(resp.error?.message || `The model stopped early (${resp.status}).`);
  const parts = (resp.output ?? []).filter((o) => o.type === "message").flatMap((o) => o.content ?? []);
  const refusal = parts.find((p) => p.type === "refusal");
  if (refusal) throw new RefusalError(refusal.refusal || "");
  const text = parts.filter((p) => p.type === "output_text").map((p) => p.text).join("");
  return nonEmpty({ message: resp, text, usage });
}

/** JSON that matches `schema`; falls back to JSON in plain text if the API refuses the schema. */
export const askJSON = makeAskJSON(
  ask,
  (e) => e?.status === 400 && (/^text\.format/.test(e?.param ?? "") || /schema/i.test(String(e?.message))),
);

/** Search tool for the prepare step. OpenAI has no per-request search cap; the prompt states the budget. */
export function prepTools() {
  return [{ type: "web_search" }];
}
