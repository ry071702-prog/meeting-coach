import { test } from "node:test";
import assert from "node:assert/strict";
import * as gemini from "../../web/providers/gemini.js";
import { EmptyAnswerError, RefusalError, describeError } from "../../web/providers/common.js";
import { fakeFetch } from "./fake.mjs";

const answer = (text, extra = {}) => ({
  json: {
    candidates: [{ content: { role: "model", parts: [{ text: "planning...", thought: true }, { text }] }, finishReason: "STOP", ...extra }],
    usageMetadata: { promptTokenCount: 100, candidatesTokenCount: 20, thoughtsTokenCount: 30, toolUsePromptTokenCount: 5 },
  },
});
const client = (f) => gemini.makeClient("test-key", { fetch: f });
const opts = { model: "gemini-flash-latest", system: "Be brief.", messages: [{ role: "user", content: "Hi" }] };

test("builds a generateContent request with the key in a header", async () => {
  const f = fakeFetch(answer("Hello"));
  await gemini.ask(client(f), {
    ...opts,
    messages: [{ role: "user", content: "a" }, { role: "assistant", content: "b" }, { role: "user", content: "c" }],
    schema: { type: "object" }, effort: "medium", maxTokens: 4000,
  });
  const { url, init, body } = f.calls[0];
  assert.equal(url, "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent");
  assert.equal(init.headers["x-goog-api-key"], "test-key");
  assert.doesNotMatch(url, /key=/); // never in the URL, where logs and history would keep it
  assert.deepEqual(body.systemInstruction, { parts: [{ text: "Be brief." }] });
  assert.deepEqual(body.contents.map((c) => c.role), ["user", "model", "user"]);
  assert.deepEqual(body.generationConfig, {
    maxOutputTokens: 65536, thinkingConfig: { thinkingLevel: "medium" }, // full room: thinking shares the cap
    responseMimeType: "application/json", responseJsonSchema: { type: "object" },
  });
  assert.equal(body.tools, undefined);
});

test("a model typed as models/<id> still hits the right URL", async () => {
  const f = fakeFetch(answer("x"));
  await gemini.ask(client(f), { ...opts, model: "models/gemini-pro-latest" });
  assert.match(f.calls[0].url, /\/models\/gemini-pro-latest:generateContent$/);
});

test("joins the answer parts, skips thoughts, and counts thinking and search as tokens", async () => {
  const r = await gemini.ask(client(fakeFetch(answer("Hello"))), opts);
  assert.equal(r.text, "Hello");
  assert.deepEqual(r.usage, { input: 105, output: 50 });
});

test("a cut-off answer is an error, not half a JSON object", async () => {
  const f = fakeFetch({ json: { candidates: [{ content: { parts: [{ text: "{\"a\":" }] }, finishReason: "MAX_TOKENS" }] } });
  await assert.rejects(gemini.ask(client(f), opts), /cut off/);
  assert.equal(f.calls.length, 1);
});

test("a safety stop or a blocked prompt is a refusal", async () => {
  await assert.rejects(gemini.ask(client(fakeFetch({ json: { candidates: [{ finishReason: "SAFETY" }] } })), opts), RefusalError);
  const blocked = gemini.ask(client(fakeFetch({ json: { promptFeedback: { blockReason: "PROHIBITED_CONTENT" } } })), opts);
  await assert.rejects(blocked, (e) => e instanceof RefusalError && /PROHIBITED_CONTENT/.test(e.message));
});

test("any other early stop is an error, not an empty answer", async () => {
  await assert.rejects(gemini.ask(client(fakeFetch({ json: { candidates: [{ content: { parts: [] }, finishReason: "OTHER" }] } })), opts), /stopped early \(OTHER\)/);
});

test("an answer with no text, or only thoughts, is an empty answer", async () => {
  const only = (content) => fakeFetch({ json: { candidates: [{ content, finishReason: "STOP" }] } });
  for (const content of [undefined, { parts: [] }, { parts: [{ text: "planning...", thought: true }] }, { parts: [{ text: " \n" }] }]) {
    await assert.rejects(gemini.ask(client(only(content)), opts), (e) => e instanceof EmptyAnswerError && describeError(e) === "e_empty");
  }
  await assert.rejects(gemini.ask(client(fakeFetch({ json: { candidates: [] } })), opts), EmptyAnswerError); // no candidate and no block reason
});

test("a wrong key reads as a key problem; other HTTP errors keep their status", async () => {
  // the shape Google returned for a made-up key on 2026-10-15
  const badKey = { status: 400, json: { error: { code: 400, message: "API key not valid. Please pass a valid API key.", status: "INVALID_ARGUMENT", details: [{ reason: "API_KEY_INVALID" }] } } };
  await assert.rejects(gemini.ask(client(fakeFetch(badKey)), opts), (e) => e.status === 401 && describeError(e) === "e401");
  const busy = { status: 429, json: { error: { code: 429, message: "Resource exhausted", status: "RESOURCE_EXHAUSTED" } } };
  await assert.rejects(gemini.ask(client(fakeFetch(busy)), opts), (e) => describeError(e) === "e429");
  await assert.rejects(gemini.ask(client(fakeFetch({ status: 503, json: null })), opts), (e) => describeError(e) === "e5xx (503)");
});

test("askJSON parses the structured reply", async () => {
  const r = await gemini.askJSON(client(fakeFetch(answer('{"ok":true}'))), { ...opts, schema: { type: "object" } });
  assert.deepEqual(r.data, { ok: true });
});

test("askJSON falls back to the schema in the instructions when the API refuses it", async () => {
  // the shape Google returned for a bad schema on 2026-10-15
  const refused = { status: 400, json: { error: { code: 400, message: "unrecognized type 'nonsense' at properties.a", status: "INVALID_ARGUMENT" } } };
  const f = fakeFetch(refused, answer('Here you go: {"ok":true}'));
  const r = await gemini.askJSON(client(f), { ...opts, schema: { type: "object" } });
  assert.deepEqual(r.data, { ok: true });
  assert.equal(f.calls[1].body.generationConfig.responseJsonSchema, undefined);
  assert.match(f.calls[1].body.systemInstruction.parts[0].text, /JSON Schema/);
});

test("askJSON reports an answer that is not JSON as an empty answer, with or without the fallback", async () => {
  await assert.rejects(gemini.askJSON(client(fakeFetch(answer('{"ok":'))), { ...opts, schema: { type: "object" } }), EmptyAnswerError);
  const refused = { status: 400, json: { error: { code: 400, message: "unrecognized type 'nonsense' at properties.a", status: "INVALID_ARGUMENT" } } };
  await assert.rejects(gemini.askJSON(client(fakeFetch(refused, answer("Sorry, no JSON today."))), { ...opts, schema: { type: "object" } }), EmptyAnswerError);
});

test("other 400s are not mistaken for a refused schema", async () => {
  const f = fakeFetch({ status: 400, json: { error: { code: 400, message: "Thinking level MINIMAL is not supported for this model.", status: "INVALID_ARGUMENT" } } });
  await assert.rejects(gemini.askJSON(client(f), { ...opts, schema: { type: "object" } }), (e) => e.status === 400);
  assert.equal(f.calls.length, 1);
});

test("the prepare step reads the given pages but does not search (Google Search grounding terms)", () => {
  assert.deepEqual(gemini.prepTools(12), [{ urlContext: {} }]);
  assert.equal(gemini.webSearch, false);
});

test("the default model is one of the listed models", () => {
  assert.ok(gemini.models.some((m) => m.id === gemini.defaultModel));
});

test("keyPattern takes Google API keys but not OpenAI's or Anthropic's", () => {
  assert.ok(gemini.keyPattern.test("AIzaSyabc"));
  for (const k of ["sk-proj-abc", "sk-ant-api03-abc", ""]) assert.ok(!gemini.keyPattern.test(k), k);
});
