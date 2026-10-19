// Runs the skill's own Python scripts in the browser with Pyodide, so scores
// are computed exactly as in the skill. The store (~/.meeting-coach) is kept in IndexedDB.
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";
const STORE = "/home/pyodide/.meeting-coach";

let py = null;
export const refs = {}; // skill files by path, also used to build prompts

async function fetchText(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`could not load ${url} (${r.status})`);
  return r.text();
}

export async function boot(onStep = () => {}) {
  if (py) return py;
  onStep("python");
  const { loadPyodide } = await import(`${PYODIDE}pyodide.mjs`);
  py = await loadPyodide({ indexURL: PYODIDE });

  onStep("skill");
  const manifest = JSON.parse(await fetchText("./manifest.json"));
  await Promise.all(manifest.files.map(async (f) => {
    const text = await fetchText(manifest.skill_base + f);
    refs[f] = text;
    const path = `/skill/${f}`;
    py.FS.mkdirTree(path.slice(0, path.lastIndexOf("/")));
    py.FS.writeFile(path, text);
  }));
  py.FS.writeFile("/skill/bridge.py", await fetchText("./bridge.py"));

  onStep("store");
  py.FS.mkdirTree(STORE);
  py.FS.mount(py.FS.filesystems.IDBFS, {}, STORE);
  await sync(true);

  py.runPython("import sys; sys.path.insert(0, '/skill'); import bridge");
  return py;
}

function sync(populate) {
  return new Promise((resolve, reject) => py.FS.syncfs(populate, (err) => (err ? reject(err) : resolve())));
}

async function withStoreLock(work) {
  // Several tabs share one IndexedDB store, and syncfs(false) replaces it with this tab's copy.
  // So: one tab at a time, and reload the store from IndexedDB right before touching it.
  if (navigator.locks?.request) return navigator.locks.request("meeting-coach-store", work);
  return work();
}

/** Call bridge.<fn>(*args) with string args; returns parsed JSON (or text for text-returning fns). */
export async function call(fn, args = [], { json = true, persist = false } = {}) {
  return withStoreLock(async () => {
    await sync(true);
    const out = py.globals.get("bridge")[fn](...args);
    if (persist) await sync(false);
    return json ? JSON.parse(out) : out;
  });
}

/** Put an uploaded or pasted transcript into the Python file system and return its path. */
export function writeInput(bytes) {
  const path = "/tmp/transcript-input";
  py.FS.writeFile(path, bytes);
  return path;
}

export function forget(path) {
  try { py.FS.unlink(path); } catch { /* already gone */ }
}
