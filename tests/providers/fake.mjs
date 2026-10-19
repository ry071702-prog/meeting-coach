// A fetch stand-in for the provider tests: answers from a queue and records what was sent.
export function fakeFetch(...replies) {
  const calls = [];
  const f = async (url, init) => {
    calls.push({ url, init, body: JSON.parse(init.body) });
    const r = replies.length > 1 ? replies.shift() : replies[0];
    const status = r.status ?? 200;
    return { ok: status < 300, status, json: async () => r.json };
  };
  f.calls = calls;
  return f;
}
