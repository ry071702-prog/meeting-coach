// Response shapes follow the examples in the Responses API reference (developers.openai.com, 2026-10-15);
// none of them was captured from the real API.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as openai from "../../web/providers/openai.js";
import { EmptyAnswerError, RefusalError, describeError } from "../../web/providers/common.js";
import { fakeFetch } from "./fake.mjs";

const answer = (text) => ({
  json: {
    status: "completed",
    output: [
      { type: "reasoning", summary: [] },
      { type: "web_search_call", status: "completed" },
      { type: "message", role: "assistant", content: [{ type: "output_text", text, annotations: [] }] },
    ],
    usage: { input_tokens: 100, output_tokens: 50, output_tokens_details: { reasoning_tokens: 30 } },
  },
});
const failure = (status, error) => ({ status, json: { error: { type: "invalid_request_error", code: null, param: null, ...error } } });
const client = (f) => openai.makeClient("test-key", { fetch: f });
const opts = { model: "gpt-6-astra", system: "Be brief.", messages: [{ role: "user", content: "Hi" }] };

test("builds a Responses request that is not stored", async () => {
  const f = fakeFetch(answer("Hello"));
  await openai.ask(client(f), {
    ...opts,
    messages: [{ role: "user", content: "a" }, { role: "assistant", content: "b" }, { role: "user", content: "c" }],
    schema: { type: "object" }, effort: "medium", maxTokens: 4000,
  });
  const { url, init, body } = f.calls[0];
  assert.equal(url, "https://api.openai.com/v1/responses");
  assert.equal(init.headers.authorization, "Bearer test-key");
  assert.equal(body.store, false); // the API keeps responses for 30 days unless told not to
  assert.equal(body.instructions, "Be brief.");
  assert.deepEqual(body.input.map((m) => m.role), ["user", "assistant", "user"]);
  assert.deepEqual(body.reasoning, { effort: "medium" });
  assert.deepEqual(body.text, { format: { type: "json_schema", name: "answer", strict: true, schema: { type: "object" } } });
  assert.equal(body.max_output_tokens, undefined); // reasoning shares the cap: leave the model's full room
  assert.equal(body.tools, undefined);
});

test("joins the message text and skips reasoning and search items", async () => {
  const r = await openai.ask(client(fakeFetch(answer("Hello"))), opts);
  assert.equal(r.text, "Hello");
  assert.deepEqual(r.usage, { input: 100, output: 50 }); // output_tokens already includes reasoning
});

test("returns the pages cited by url_citation annotations, each once", async () => {
  const reply = answer("See the profile.");
  reply.json.output[2].content[0].annotations = [
    { type: "url_citation", start_index: 0, end_index: 7, url: "https://a.example/profile", title: "Profile" },
    { type: "file_citation", file_id: "file_1" },
    { type: "url_citation", start_index: 8, end_index: 15, url: "https://a.example/profile", title: "Profile" },
  ];
  const r = await openai.ask(client(fakeFetch(reply)), opts);
  assert.deepEqual(r.sources, [{ url: "https://a.example/profile", title: "Profile" }]);
  assert.deepEqual((await openai.ask(client(fakeFetch(answer("Hi"))), opts)).sources, []);
});

test("an answer with only reasoning and search items is an empty answer", async () => {
  const output = answer("x").json.output.slice(0, 2);
  const f = fakeFetch({ json: { status: "completed", output, usage: { input_tokens: 100, output_tokens: 50 } } });
  await assert.rejects(openai.ask(client(f), opts), (e) => e instanceof EmptyAnswerError && describeError(e) === "e_empty");
});

test("a refusal in the message is a RefusalError", async () => {
  const f = fakeFetch({ json: { status: "completed", output: [{ type: "message", content: [{ type: "refusal", refusal: "I can't help with that." }] }] } });
  await assert.rejects(openai.ask(client(f), opts), (e) => e instanceof RefusalError && /can't help/.test(e.message));
});

test("an incomplete answer is an error, not half a JSON object", async () => {
  const cut = (reason) => fakeFetch({ json: { status: "incomplete", incomplete_details: { reason }, output: [{ type: "message", content: [{ type: "output_text", text: "{\"a\":" }] }] } });
  await assert.rejects(openai.ask(client(cut("max_output_tokens")), opts), /cut off/);
  await assert.rejects(openai.ask(client(cut("content_filter")), opts), RefusalError);
  await assert.rejects(openai.ask(client(cut("max_messages")), opts), /stopped early \(max_messages\)/);
});

test("a failed response reports its error", async () => {
  const f = fakeFetch({ json: { status: "failed", error: { code: "server_error", message: "Something broke." }, output: [] } });
  await assert.rejects(openai.ask(client(f), opts), /Something broke/);
});

test("HTTP errors map to the shared messages", async () => {
  const t = (k) => k;
  const run = (reply) => openai.ask(client(fakeFetch(reply)), opts).catch((e) => e);
  assert.equal(describeError(await run(failure(401, { code: "invalid_api_key", message: "Incorrect API key provided." })), t), "e401");
  const quota = await run(failure(429, { type: "insufficient_quota", code: "credit_balance_exhausted", message: "You exceeded your current quota." }));
  assert.equal(describeError(quota, t), "e429");
  assert.equal(quota.type, "insufficient_quota"); // kept so the screen can tell "out of credit" from "slow down"
  assert.equal(describeError(await run({ status: 503, json: null }), t), "e5xx (503)");
});

test("askJSON parses the structured reply", async () => {
  const r = await openai.askJSON(client(fakeFetch(answer("{\"a\":1}"))), { ...opts, schema: { type: "object" } });
  assert.deepEqual(r.data, { a: 1 });
});

test("askJSON retries with the schema in the instructions when the schema is refused", async () => {
  const f = fakeFetch(failure(400, { param: "text.format.schema", message: "Invalid schema for response_format 'answer'." }), answer("Sure: {\"a\":2}"));
  const r = await openai.askJSON(client(f), { ...opts, schema: { type: "object" } });
  assert.deepEqual(r.data, { a: 2 });
  assert.equal(f.calls[1].body.text, undefined);
  assert.match(f.calls[1].body.instructions, /^Be brief\.\n\nReply with only a JSON object/);
});

test("askJSON reports an answer that is not JSON as an empty answer", async () => {
  await assert.rejects(openai.askJSON(client(fakeFetch(answer("{\"a\":"))), { ...opts, schema: { type: "object" } }), EmptyAnswerError);
});

test("a 400 about something else is not mistaken for a refused schema", async () => {
  const f = fakeFetch(failure(400, { param: "reasoning.effort", message: "Unsupported value: 'none'." }));
  await assert.rejects(openai.askJSON(client(f), { ...opts, schema: { type: "object" } }), (e) => e.status === 400);
  assert.equal(f.calls.length, 1);
});

test("prepTools asks for web search", () => {
  assert.deepEqual(openai.prepTools(5), [{ type: "web_search" }]);
});

test("the default model is in the list", () => {
  assert.ok(openai.models.some((m) => m.id === openai.defaultModel));
});

test("keyPattern takes OpenAI's key formats but not Anthropic's or Google's", () => {
  for (const k of ["sk-proj-abc", "sk-svcacct-abc", "sk-abc123"]) assert.ok(openai.keyPattern.test(k), k);
  for (const k of ["sk-ant-api03-abc", "AIzaSyabc", ""]) assert.ok(!openai.keyPattern.test(k), k);
});
