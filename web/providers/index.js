// The AI providers the app can call. Each module has the same shape (anthropic.js is the reference):
//   id, label, keyPlaceholder, keyPattern (how its keys start), keyUrl, status ("untested" | "experimental" | "tested"), models, defaultModel,
//   webSearch (optional; false when the prepare step may only read the given URLs)
//   makeClient(key) / ask(client, {model, system, messages, tools, schema, effort, maxTokens}) -> {text, usage: {input, output}}
//   askJSON(client, opts) -> {data, usage} / prepTools(searches) -> the web tools for the prepare step
import * as anthropic from "./anthropic.js";
import * as openai from "./openai.js";
import * as gemini from "./gemini.js";

export { describeError, sourcesMarkdown } from "./common.js";
export const PROVIDERS = { anthropic, openai, gemini }; // the order shown in Settings
export const DEFAULT_PROVIDER = "anthropic";

/**
 * The AI whose keys look like `key`, or null when none does (a format we do not know is let through).
 * Every word is looked at, so a key pasted as `ANTHROPIC_API_KEY=sk-ant-…`, in quotes or after "Bearer" is still known.
 * @example keyOwner("AIza...") === "gemini"
 */
export function keyOwner(key) {
  const words = keyWords(key);
  return Object.values(PROVIDERS).find((p) => p.keyPattern && words.some((w) => p.keyPattern.test(w)))?.id ?? null;
}

/**
 * The key out of what was pasted: the word that looks like some AI's key, else the text trimmed.
 * @example pastedKey('export ANTHROPIC_API_KEY="sk-ant-abc"') === "sk-ant-abc"
 */
export function pastedKey(text) {
  return keyWords(text).find((w) => Object.values(PROVIDERS).some((p) => p.keyPattern?.test(w))) ?? String(text).trim();
}

function keyWords(text) {
  return String(text).replace(/[\u200B-\u200D\u2060\uFEFF]/g, "").split(/[\s"'`=:]+/).filter(Boolean);
}

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
