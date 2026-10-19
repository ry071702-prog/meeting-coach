"""Glue between the web app and the skill's scripts, running inside Pyodide.

Every function takes and returns JSON strings so the JavaScript side never
handles Python objects. The store lives at ~/.meeting-coach, which the app
mounts on IndexedDB so it survives page reloads.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.environ.get("MC_SKILL_SCRIPTS", "/skill/scripts"))
sys.dont_write_bytecode = True

import assign_speakers  # noqa: E402
import learnings  # noqa: E402
import metrics as metrics_mod  # noqa: E402
import parse_transcript  # noqa: E402
import score as score_mod  # noqa: E402
import verify_evidence  # noqa: E402
from common import load_config, store_dir  # noqa: E402


def _cfg():
    return load_config()


def _root():
    return store_dir(_cfg())


def _j(x):
    return json.dumps(x, ensure_ascii=False)


def _safe(fn):
    """Return {"error": ...} instead of letting a Python traceback reach the page."""
    def wrapper(*args):
        try:
            return fn(*args)
        except SystemExit as e:
            return _j({"error": str(e)})
        except Exception as e:  # noqa: BLE001 - shown to the user as a message
            return _j({"error": f"{type(e).__name__}: {e}"})
    wrapper.__name__ = fn.__name__
    return wrapper


@_safe
def parse(path, lang=""):
    try:
        text = parse_transcript.read_text(path)
    except SystemExit as e:  # .docx / PDF / undecodable: tell the user what to do
        return _j({"error": str(e)})
    return _j(parse_transcript.parse(text, lang or None))


@_safe
def assign(transcript, spec):
    return _j(assign_speakers.assign(json.loads(transcript), json.loads(spec)))


@_safe
def measure(transcript, meta):
    return _j(metrics_mod.compute(json.loads(transcript), json.loads(meta), _cfg()))


@_safe
def verify(judgement, transcript):
    return _j(verify_evidence.verify(json.loads(judgement), json.loads(transcript)))


@_safe
def score(judgement, meta, metrics):
    res = score_mod.compute(json.loads(judgement), json.loads(meta), json.loads(metrics), _cfg())
    if res.get("errors"):
        return _j({"errors": res["errors"]})
    lang = json.loads(meta).get("language") or "en"
    return _j({"result": res, "markdown": score_mod.to_markdown(res, lang)})


@_safe
def save(judgement, score_res, transcript, meta):
    try:
        return _j(learnings.save(json.loads(judgement), json.loads(score_res), json.loads(transcript),
                                 json.loads(meta), _cfg(), _root()))
    except ValueError as e:
        return _j({"error": str(e)})


@_safe
def summary():
    return _j(learnings.summary(learnings.load_state(_root())))


@_safe
def prep_save(prep):
    try:
        return _j(learnings.prep_save(json.loads(prep), _cfg(), _root()))
    except ValueError as e:
        return _j({"error": str(e)})


@_safe
def prep_find(date=""):
    return _j(learnings.prep_find(_root(), date or None))


def export_block(lang="ja"):
    root = _root()
    return learnings.render(learnings.load_state(root), lang, learnings.open_preps(root))


@_safe
def import_block(text, lang="ja"):
    if learnings.BLOCK_TAG not in text:
        return _j({"error": "not a meeting-coach hand-over block (its first line must be the meeting-coach learnings tag)"})
    state = learnings.parse_block(text)
    preps = state.pop("preps", [])
    root = _root()
    (root / "prep").mkdir(parents=True, exist_ok=True)
    for pr in preps:
        if learnings.PREP_ID.fullmatch(pr.get("id", "")):
            learnings.write_json(pr, root / "prep" / f"{pr['id']}.json")
    learnings.save_state(root, state, lang)
    return _j({"actions": len(state["actions"]), "habits": len(state["habits"]), "plans": len(preps)})


@_safe
def history():
    p = _root() / "history.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.is_file() else []
    return _j(rows)


def learnings_md():
    p = _root() / "learnings.md"
    return p.read_text(encoding="utf-8") if p.is_file() else ""


@_safe
def backup_info(data):
    d = json.loads(data)
    if d.get("format") != "meeting-coach-backup":
        return _j({"error": "not a meeting-coach backup"})
    files = [f for f in d.get("files", {}) if RESTORABLE.fullmatch(f)]
    return _j({"files": len(files), "reviews": sum(f.startswith("reviews/") for f in files),
               "plans": sum(f.startswith("prep/") for f in files)})


@_safe
def backup():
    root = _root()
    files = {}
    if root.is_dir():
        for f in sorted(root.rglob("*")):
            if f.is_file():
                files[str(f.relative_to(root))] = f.read_text(encoding="utf-8")
    return _j({"format": "meeting-coach-backup", "version": 1, "files": files})


RESTORABLE = re.compile(r"(learnings\.json|learnings\.md|history\.jsonl|prep/P-\d{8}-\d+\.json|reviews/[\w.-]+\.md)")


@_safe
def restore(data):
    d = json.loads(data)
    if d.get("format") != "meeting-coach-backup":
        return _j({"error": "not a meeting-coach backup"})
    root = _root().resolve()
    n = 0
    for rel, text in d.get("files", {}).items():
        if not RESTORABLE.fullmatch(rel):
            continue  # only data files: never config.json or anything that changes where or how data is kept
        target = (root / rel).resolve()
        if root not in target.parents:
            continue  # never write outside the store
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        n += 1
    return _j({"restored": n})


@_safe
def wipe():
    root = _root()
    n = 0
    if root.is_dir():
        for f in sorted(root.rglob("*"), reverse=True):
            if f.is_file():
                f.unlink()
                n += 1
            elif f.is_dir() and f != root:
                f.rmdir()
    return _j({"deleted": n})
