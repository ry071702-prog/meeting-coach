// Response shapes follow the Messages API reference; none of them was captured from the real API.
import { test } from "node:test";
import assert from "node:assert/strict";
import { EmptyAnswerError, RefusalError } from "../../web/providers/common.js";
import "./cdn-stub.mjs";

const anthropic = await import("../../web/providers/anthropic.js");

/** A client whose create calls answer from a queue (an Error is thrown) and record a copy of each request. */
function fakeClient(...replies) {
  const calls = [];
  const create = (beta) => async (params) => {
    calls.push({ beta, params: structuredClone(params) });
    const r = replies.length > 1 ? replies.shift() : replies[0];
    if (r instanceof Error) throw r;
    return r;
  };
  return { calls, beta: { messages: { create: create(true) } }, messages: { create: create(false) } };
}
const reply = (content, stop_reason = "end_turn") => ({ content, stop_reason, usage: { input_tokens: 10, output_tokens: 5 } });
const text = (t, citations) => ({ type: "text", text: t, ...(citations ? { citations } : {}) });
const httpError = (status, message) => Object.assign(new Error(message), { status });
const opts = { model: "claude-opus-5-5", system: "Be brief.", messages: [{ role: "user", content: "Hi" }] };

test("makeClient keeps the user's key in the browser", () => {
  const c = anthropic.makeClient("test-key");
  assert.deepEqual(c.opts, { apiKey: "test-key", dangerouslyAllowBrowser: true });
});

test("the first request asks for the server-side fallback, with effort, schema and tools", async () => {
  const c = fakeClient(reply([text("Hello")]));
  const tools = anthropic.prepTools(3);
  const r = await anthropic.ask(c, { ...opts, schema: { type: "object" }, effort: "low", tools });
  const { beta, params } = c.calls[0];
  assert.equal(beta, true);
  assert.deepEqual(params.betas, ["server-side-fallback-2026-07-01"]);
  assert.equal(params.fallbacks, "default");
  assert.deepEqual(params.output_config, { effort: "low", format: { type: "json_schema", schema: { type: "object" } } });
  assert.equal(params.max_tokens, 16000);
  assert.equal(params.system, "Be brief.");
  assert.deepEqual(params.tools.map((t) => [t.name, t.max_uses]), [["web_search", 3], ["web_fetch", 10]]);
  assert.equal(r.text, "Hello");
  assert.deepEqual(r.usage, { input: 10, output: 5 });
});

test("an account without the fallback beta is asked again once without it", async () => {
  const c = fakeClient(httpError(400, "fallbacks is not available for this account"), reply([text("Hello")]));
  const r = await anthropic.ask(c, opts);
  assert.deepEqual(c.calls.map((x) => x.beta), [true, false]);
  assert.equal(c.calls[1].params.betas, undefined);
  assert.equal(r.text, "Hello");
});

test("a refusal is a RefusalError carrying the explanation", async () => {
  const c = fakeClient({ ...reply([], "refusal"), stop_details: { explanation: "Not this one." } });
  await assert.rejects(anthropic.ask(c, opts), (e) => e instanceof RefusalError && /Not this one/.test(e.message));
});

test("an answer cut off by max_tokens is asked again once with twice the room", async () => {
  const c = fakeClient(reply([text("half")], "max_tokens"), reply([text("whole")]));
  const r = await anthropic.ask(c, opts);
  assert.deepEqual(c.calls.map((x) => x.params.max_tokens), [16000, 32000]);
  assert.equal(c.calls[1].params.messages.length, 1); // the cut-off half is not sent back
  assert.equal(r.text, "whole");
  const again = fakeClient(reply([text("half")], "max_tokens"));
  await assert.rejects(anthropic.ask(again, opts), /cut off/);
  assert.equal(again.calls.length, 2);
});

test("a paused turn is sent back so the model continues, and usage adds up", async () => {
  const paused = [{ type: "server_tool_use", id: "srvtoolu_1", name: "web_search", input: { query: "x" } }];
  const c = fakeClient(reply(paused, "pause_turn"), reply([text("done")]));
  const r = await anthropic.ask(c, opts);
  assert.deepEqual(c.calls[1].params.messages, [...opts.messages, { role: "assistant", content: paused }]);
  assert.equal(r.text, "done");
  assert.deepEqual(r.usage, { input: 20, output: 10 });
});

test("text written before a paused turn is kept, with its citations, and dropped when the answer is asked again", async () => {
  const a = { type: "web_search_result_location", url: "https://a.example/", title: "A", cited_text: "x", encrypted_index: "e" };
  const b = { ...a, url: "https://b.example/", title: "B" };
  const search = { type: "server_tool_use", id: "srvtoolu_1", name: "web_search", input: { query: "x" } };
  const c = fakeClient(reply([text("First, A says so.", [a]), search], "pause_turn"), reply([text(" Then B.", [b])]));
  const r = await anthropic.ask(c, opts);
  assert.equal(r.text, "First, A says so. Then B.");
  assert.deepEqual(r.sources, [{ url: "https://a.example/", title: "A" }, { url: "https://b.example/", title: "B" }]);
  const cut = fakeClient(reply([text("early", [a]), search], "pause_turn"), reply([text("half")], "max_tokens"), reply([text("whole", [b])]));
  const again = await anthropic.ask(cut, opts);
  assert.equal(again.text, "whole");
  assert.deepEqual(again.sources, [{ url: "https://b.example/", title: "B" }]);
});

test("returns each page cited by a search result once; fetched-page citations have no URL and drop out", async () => {
  const found = { type: "web_search_result_location", url: "https://a.example/profile", title: "Profile", cited_text: "x", encrypted_index: "e" };
  const c = fakeClient(reply([
    text("According to the profile", [found]),
    text(", and the page", [{ type: "char_location", document_title: "Fetched", document_index: 0, start_char_index: 0, end_char_index: 4, cited_text: "x" }, found]),
    text(" and the news", [{ ...found, url: "https://b.example/news", title: "News" }]),
    text("."),
  ]));
  const r = await anthropic.ask(c, opts);
  assert.equal(r.text, "According to the profile, and the page and the news.");
  assert.deepEqual(r.sources, [{ url: "https://a.example/profile", title: "Profile" }, { url: "https://b.example/news", title: "News" }]);
  assert.deepEqual((await anthropic.ask(fakeClient(reply([text("Hi")])), opts)).sources, []);
});

test("an answer with no text is an empty answer", async () => {
  const c = fakeClient(reply([{ type: "web_search_tool_result", tool_use_id: "srvtoolu_1", content: [] }]));
  await assert.rejects(anthropic.ask(c, opts), (e) => e instanceof EmptyAnswerError);
});

test("askJSON writes the schema into the instructions when the model refuses it", async () => {
  const c = fakeClient(httpError(400, "output_config.format is not supported for this model"), reply([text('Here: {"a": 1}')]));
  const r = await anthropic.askJSON(c, { ...opts, schema: { type: "object" } });
  assert.deepEqual(r.data, { a: 1 });
  assert.equal(c.calls[1].params.output_config.format, undefined);
  assert.match(c.calls[1].params.system, /^Be brief\.\n\nReply with only a JSON object/);
});
