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

/** Pull the JSON object out of a reply that was asked for JSON in plain text. */
export function extractJSON(text) {
  const m = String(text).match(/\{[\s\S]*\}/);
  if (!m) throw new Error("The model did not return JSON.");
  return JSON.parse(m[0]);
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
      return { data: parse(r.text, extractJSON), usage: r.usage };
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
