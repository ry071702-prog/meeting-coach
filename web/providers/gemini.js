// Gemini (Google), called with fetch straight from the browser with the user's own key.
// Nothing passes through any server other than Google's.
import { ApiError, EmptyAnswerError, RefusalError, makeAskJSON, nonEmpty } from "./common.js";

export const id = "gemini";
export const label = "Gemini";
export const keyPlaceholder = "AIza...";
export const keyPattern = /^AIza/;
export const keyUrl = "https://aistudio.google.com/apikey";
// The fictional examples pass end to end against the real API, but re-scoring one moved it a band:
// 3 examples x 3 runs on 2026-10-15, ja-1on1-plain scored S once and A twice
export const status = "experimental";
// Grounding with Google Search must be shown with Google's Search Suggestions and may be used only in an app
// the key holder owns and runs (Gemini API terms, effective 2026-03-23, page last updated 2026-04-28); we judge
// that this app does neither, so it only reads URLs
export const webSearch = false;
export const models = [
  { id: "gemini-flash-latest", label: "Gemini Flash" },
  { id: "gemini-pro-latest", label: "Gemini Pro" },
];
export const defaultModel = models[0].id;

const BASE = "https://generativelanguage.googleapis.com/v1beta/models/";
const MAX_OUTPUT = 65536; // outputTokenLimit of both models above (models.get, 2026-10-15)
// finish reasons that mean a filter stopped the answer
const DECLINED = new Set(["SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY"]);

/** @param {{fetch?: typeof fetch}} [opts] a fetch to use instead of the browser's (tests) */
export function makeClient(apiKey, { fetch: f } = {}) {
  return { apiKey, fetch: f ?? ((...a) => fetch(...a)) };
}

async function post(client, model, body) {
  const res = await client.fetch(`${BASE}${encodeURIComponent(model.replace(/^models\//, ""))}:generateContent`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-goog-api-key": client.apiKey },
    body: JSON.stringify(body),
  });
  const j = await res.json().catch(() => null);
  if (!res.ok) {
    const message = j?.error?.message || `HTTP ${res.status}`;
    // a wrong key comes back as 400 INVALID_ARGUMENT; report it as the key problem it is
    const badKey = j?.error?.details?.some((d) => d?.reason === "API_KEY_INVALID");
    throw new ApiError(badKey ? 401 : res.status, message);
  }
  return j;
}

/**
 * One request. `maxTokens` is not used: thinking shares Gemini's output cap (one judgement thought for
 * 10,002 tokens on 2026-10-15, more than half of the 16000 asked for), and a cap costs nothing until it
 * is used, so every call gets the full room instead of being cut off and paid for twice.
 * @returns {Promise<{message: object, text: string, usage: {input: number, output: number}}>}
 */
export async function ask(client, { model, system, messages, tools, schema, effort = "high" }) {
  const body = {
    ...(system ? { systemInstruction: { parts: [{ text: system }] } } : {}),
    contents: messages.map((m) => ({ role: m.role === "assistant" ? "model" : "user", parts: [{ text: m.content }] })),
    generationConfig: {
      maxOutputTokens: MAX_OUTPUT,
      thinkingConfig: { thinkingLevel: effort }, // low, medium and high are the same words here
      ...(schema ? { responseMimeType: "application/json", responseJsonSchema: schema } : {}),
    },
    ...(tools ? { tools } : {}),
  };
  const resp = await post(client, model, body);
  const u = resp.usageMetadata ?? {};
  const usage = {
    input: (u.promptTokenCount ?? 0) + (u.toolUsePromptTokenCount ?? 0),
    output: (u.candidatesTokenCount ?? 0) + (u.thoughtsTokenCount ?? 0), // thinking is billed as output
  };
  const cand = resp.candidates?.[0];
  if (!cand) {
    const why = resp.promptFeedback?.blockReason;
    throw why ? new RefusalError(`(${why})`) : new EmptyAnswerError("The model returned no answer.");
  }
  if (DECLINED.has(cand.finishReason)) throw new RefusalError(`(${cand.finishReason})`);
  if (cand.finishReason === "MAX_TOKENS") throw new Error("The answer was too long and got cut off.");
  if (cand.finishReason && cand.finishReason !== "STOP") throw new Error(`The model stopped early (${cand.finishReason}).`);
  const text = (cand.content?.parts ?? []).filter((p) => !p.thought && typeof p.text === "string").map((p) => p.text).join("");
  return nonEmpty({ message: resp, text, usage });
}

/** JSON that matches `schema`; falls back to JSON in plain text if the API refuses the schema. */
export const askJSON = makeAskJSON(ask, (e) => e?.status === 400 && /schema|unrecognized type|properties\./i.test(String(e?.message)));

/** Tools for the prepare step: read the pages the user gave, without searching (see webSearch). */
export function prepTools() {
  return [{ urlContext: {} }];
}
