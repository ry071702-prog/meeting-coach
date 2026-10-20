// What every AI provider shares: the error kinds, the JSON fallback and the error messages.

export class RefusalError extends Error {}

/** The model finished normally but left nothing usable: no text, or JSON that does not parse. */
export class EmptyAnswerError extends Error {}

/** An HTTP error from a provider called with fetch; carries `status` the way the Anthropic SDK's errors do. */
export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

/** Every provider's ask ends with this, so an empty reply never reaches the screen or the next call. */
export function nonEmpty(r) {
  if (!r.text.trim()) throw new EmptyAnswerError("The model returned an empty answer.");
  return r;
}

/**
 * The web pages a reply cites, each once, in the order first cited. Citations without an http(s) URL
 * (a fetched page cited by character range) are left out; the screen can only link to a URL.
 * @param {Array<{url?: string, title?: string}>} cites
 * @example citedSources([{url: "https://a.example", title: "A"}, {url: "https://a.example"}]) // [{url: "https://a.example", title: "A"}]
 */
export function citedSources(cites) {
  const seen = new Map();
  for (const c of cites ?? []) {
    const url = typeof c?.url === "string" ? c.url : "";
    if (!/^https?:\/\//i.test(url) || seen.has(url)) continue;
    seen.set(url, { url, title: (typeof c.title === "string" && c.title.trim()) || url });
  }
  return [...seen.values()];
}

/**
 * Markdown listing the cited pages that `text` does not already link, under `heading`; "" when there are none.
 * The plan template has the model write its own Sources list, so only the pages it left out are added.
 * The app renders this apart from the text, so an unclosed fence or comment in the reply cannot swallow it.
 * @example sourcesMarkdown("See https://a.example", [{url: "https://a.example/?utm_source=openai", title: "A"}, {url: "https://b.example", title: "B"}], "Additional sources")
 * // "### Additional sources\n\n- [B](<https://b.example>)"
 */
export function sourcesMarkdown(text, sources, heading) {
  const inText = (String(text).match(URL_IN_TEXT) ?? []).map((u) => samePage(u.replace(/[.,;:!?'*_]+$/, "")));
  const missing = (sources ?? []).filter((s) => !inText.includes(samePage(s.url)));
  if (!missing.length) return "";
  // one line per page: a newline in a title would start a block, and brackets would end the link early
  const title = (s) => s.title.replace(/\s+/g, " ").trim().replace(/[\\[\]<>*_`]/g, "\\$&");
  const url = (s) => s.url.replace(/[<>\s\\]/g, encodeURIComponent);
  return `### ${heading}\n\n${missing.map((s) => `- [${title(s)}](<${url(s)}>)`).join("\n")}`;
}

// a URL as the model writes it: balanced (…) as in Wikipedia's "John_Smith_(politician)", non-ASCII paths
// left undecoded; it stops at a bracket that does not belong to it and at Japanese punctuation
const URL_IN_TEXT = /https?:\/\/(?:\([^\s()<>]*\)|[^\s()<>"`[\]{}|\\^、。，．「」『』（）【】〈〉《》・：；！？])+/g;

/** A URL without tracking parameters, fragment and trailing slash, to tell whether two links are the same page. */
function samePage(u) {
  try {
    const x = new URL(u);
    for (const k of [...x.searchParams.keys()]) if (k.startsWith("utm_")) x.searchParams.delete(k);
    x.hash = "";
    return x.href.replace(/\/$/, "");
  } catch {
    return u;
  }
}

/**
 * Pull the JSON object out of a reply that was asked for JSON in plain text. Prose around it may hold
 * braces of its own ("fields like {name}", "return {} when empty", a format example before the answer),
 * so every balanced top-level {...} is tried. The last one holding every `required` key wins; failing
 * that, the last non-empty one (an answer comes after examples and drafts), and {} only when nothing else parses.
 * @param {string[]} [required] the schema's required keys, which tell the answer from an example after it
 * @example extractJSON('Fields like {name}. {"goal": "x"}') // {goal: "x"}
 */
export function extractJSON(text, required = []) {
  const s = String(text);
  let whole = null;
  let last = null;
  let lastEmpty = null;
  for (let start = s.indexOf("{"); start !== -1; start = s.indexOf("{", start + 1)) {
    const end = closingBrace(s, start);
    if (end === -1) continue;
    try {
      const value = JSON.parse(s.slice(start, end + 1));
      const keys = value && typeof value === "object" ? Object.keys(value) : [];
      if (required.length && required.every((k) => keys.includes(k))) whole = { value };
      if (keys.length) last = { value };
      else lastEmpty = { value };
      start = end; // the objects inside this one are shorter; skip them
    } catch { /* prose that only looks like JSON; try the next brace */ }
  }
  const found = whole ?? last ?? lastEmpty;
  if (!found) throw new Error("The model did not return JSON.");
  return found.value;
}

/** Index of the } that closes the { at `start`, skipping braces inside strings; -1 if it never closes. */
function closingBrace(s, start) {
  let depth = 0;
  let inString = false;
  for (let i = start; i < s.length; i++) {
    const ch = s[i];
    if (inString) {
      if (ch === "\\") i++;
      else if (ch === '"') inString = false;
    } else if (ch === '"') inString = true;
    else if (ch === "{") depth++;
    else if (ch === "}" && --depth === 0) return i;
  }
  return -1;
}

function parse(text, read = JSON.parse) {
  try {
    return read(text);
  } catch {
    throw new EmptyAnswerError("The model's answer was not valid JSON.");
  }
}

/**
 * Build askJSON from a provider's ask: parse the structured reply, and if the API refuses the
 * schema (an older model or account), ask again with the schema written into the instructions.
 * @param {(e: any) => boolean} isSchemaRejection the provider's test for "the schema was refused"
 * @example export const askJSON = makeAskJSON(ask, (e) => e?.status === 400 && /schema/i.test(e.message));
 */
export function makeAskJSON(ask, isSchemaRejection) {
  return async function askJSON(client, opts) {
    let r;
    try {
      r = await ask(client, opts);
    } catch (e) {
      if (!isSchemaRejection(e)) throw e;
      r = await ask(client, {
        ...opts,
        schema: undefined,
        system: `${opts.system}\n\nReply with only a JSON object matching this JSON Schema, no prose:\n${JSON.stringify(opts.schema)}`,
      });
      return { data: parse(r.text, (t) => extractJSON(t, opts.schema?.required)), usage: r.usage };
    }
    return { data: parse(r.text), usage: r.usage };
  };
}

/** @param t lookup for localized messages (keys e_refused, e_empty, e401, e403, e404, e429, e5xx, e400) */
export function describeError(e, t = (k) => k) {
  if (e instanceof RefusalError) return `${t("e_refused")} ${e.message}`;
  if (e instanceof EmptyAnswerError) return t("e_empty");
  const s = e?.status;
  if (s === 401) return t("e401");
  if (s === 403) return t("e403");
  if (s === 404) return t("e404"); // a mistyped or retired model name
  if (s === 429) return t("e429");
  if (s >= 500) return `${t("e5xx")} (${s})`;
  if (s === 400) return `${t("e400")} ${e?.message ?? ""}`;
  return e?.message ?? String(e);
}
