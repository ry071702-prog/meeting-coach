// The AI providers the app can call. Each module has the same shape (anthropic.js is the reference):
//   id, label, keyPlaceholder, keyUrl, status ("untested" | "experimental" | "tested"), models, defaultModel,
//   webSearch (optional; false when the prepare step may only read the given URLs)
//   makeClient(key) / ask(client, {model, system, messages, tools, schema, effort, maxTokens}) -> {text, usage: {input, output}}
//   askJSON(client, opts) -> {data, usage} / prepTools(searches) -> the web tools for the prepare step
import * as anthropic from "./anthropic.js";
import * as openai from "./openai.js";
import * as gemini from "./gemini.js";

export { describeError } from "./common.js";
export const PROVIDERS = { anthropic, openai, gemini }; // the order shown in Settings
export const DEFAULT_PROVIDER = "anthropic";

/**
 * Bind a provider to the user's key, so the app calls one object.
 * @example const c = connect("anthropic", key); const r = await c.ask({ model, system, messages });
 */
export function connect(id, apiKey) {
  const p = PROVIDERS[id];
  const client = p.makeClient(apiKey);
  return {
    provider: p,
    ask: (opts) => p.ask(client, opts),
    askJSON: (opts) => p.askJSON(client, opts),
    prepTools: (searches) => p.prepTools(searches),
  };
}
