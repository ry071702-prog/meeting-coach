#!/usr/bin/env python3
"""Keep what was learned from each review, so the next review can check it.

Store (default ~/.meeting-coach, see config "store_dir"):
  learnings.json   habits seen, next actions (open / done), things that worked
  learnings.md     the same, readable
  history.jsonl    one line of scores and levels per review (no names)
  reviews/         one redacted markdown file per review

Only the user's own quotes are stored. Other participants' names are replaced
by their role ("上司1", "External1") and their words are not kept.

Usage:
  python3 learnings.py open-actions [--store DIR]
  python3 learnings.py save --judgement J --score S --transcript T --meta M [--store DIR]
  python3 learnings.py export [--store DIR]          # paste-able block (for chat-only environments)
  python3 learnings.py import BLOCK.md [--store DIR] # restore from a pasted block
  python3 learnings.py summary [--store DIR]          # top habits + open actions, for prepare mode
  python3 learnings.py prep-save --prep PREP.json     # keep a meeting plan (no names, no profile text)
  python3 learnings.py prep-find [--date YYYY-MM-DD]  # the plan to compare a review against
  python3 learnings.py config                         # settings in effect (default + your config.json)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep the skill folder clean

from common import load_config, load_locale, normalize, read_json, store_dir, write_json
from score import to_markdown
from verify_evidence import check_item

BLOCK_TAG = "<!-- meeting-coach learnings v1 -->"
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
PREP_ID = re.compile(r"P-\d{8}-\d+")
TYPES = ("meeting", "one-on-one", "external")


def _check_date(date) -> str:
    if not isinstance(date, str) or not DATE.fullmatch(date):
        raise ValueError(f"date must be YYYY-MM-DD, got {date!r}")
    dt.date.fromisoformat(date)
    return date
HABIT_ID = re.compile(r"[a-z][a-z0-9_]{1,40}")


def _empty() -> dict:
    return {"version": 1, "habits": {}, "actions": [], "worked": []}


def load_state(root: Path) -> dict:
    p = root / "learnings.json"
    return read_json(p) if p.is_file() else _empty()


def open_preps(root: Path) -> list[dict]:
    folder = root / "prep"
    if not folder.is_dir():
        return []
    return [p for p in (read_json(f) for f in sorted(folder.glob("P-*.json"))) if not p.get("reviewed")]


def save_state(root: Path, state: dict, lang: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    write_json(state, root / "learnings.json")
    (root / "learnings.md").write_text(render(state, lang, open_preps(root)), encoding="utf-8")


def render(state: dict, lang: str = "en", preps: list | None = None) -> str:
    ja = lang == "ja"
    out = [BLOCK_TAG, "## " + ("自分の癖" if ja else "Habits")]
    for hid, h in sorted(state["habits"].items(), key=lambda kv: -kv[1]["count"]):
        out.append(f"- {hid}: {h['label']} ({h['count']}x, last {h['last_seen']})")
    out.append("## " + ("未完の次アクション" if ja else "Open actions"))
    for a in state["actions"]:
        if a["status"] == "open":
            misses = sum(1 for c in a["checks"] if c["done"] is False)
            out.append(f"- [{a['id']}] {a['text']} (since {a['created']}, {a['meeting_type']}, missed {misses}x)")
    out.append("## " + ("できた次アクション" if ja else "Done actions"))
    for a in state["actions"]:
        if a["status"] == "done":
            out.append(f"- [{a['id']}] {a['text']} (done {a.get('done_date', '')})")
    out.append("## " + ("続けること" if ja else "Keep doing"))
    for w in state["worked"][-10:]:
        out.append(f"- {w['text']} ({w['date']})")
    out.append("## " + ("照合前の準備" if ja else "Plans not yet reviewed"))
    for pr in preps or []:
        pos = f"/{pr['my_position']}" if pr.get("my_position") else ""
        out.append(f"- [{pr['id']}] {pr['date']} {pr['meeting_type']}{pos} {pr.get('scheduled_minutes') or '-'}min"
                   f" | goal: {pr.get('goal', '')} | aims: {' / '.join(pr.get('intents', []))}")
    return "\n".join(out) + "\n"


def parse_block(text: str) -> dict:
    """Inverse of render(), for chat-only environments where files do not persist.

    Open plans come back under state["preps"]; `import` writes them to <store>/prep/.
    """
    state, section = _empty(), None
    state["preps"] = []
    for line in text.splitlines():
        m = re.match(r"- \[(P-\d{8}-\d+)\] (\d{4}-\d{2}-\d{2}) ([\w-]+)(?:/(\w+))? (\d+|-)min \| goal: (.*?) \| aims: (.*)$", line)
        if m and section in ("照合前の準備", "Plans not yet reviewed"):
            state["preps"].append({"id": m[1], "date": m[2], "meeting_type": m[3], "my_position": m[4],
                                   "stage": None, "scheduled_minutes": None if m[5] == "-" else int(m[5]),
                                   "goal": m[6], "focus_action_ids": [],
                                   "intents": [x for x in m[7].split(" / ") if x], "reviewed": False})
            continue
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        m = re.match(r"- (\w+): (.*) \((\d+)x, last ([\d-]+)\)$", line)
        if m and section in ("自分の癖", "Habits"):
            state["habits"][m[1]] = {"label": m[2], "count": int(m[3]), "first_seen": m[4], "last_seen": m[4]}
            continue
        m = re.match(r"- \[([\w-]+)\] (.*) \(since ([\d-]+), ([\w/-]+), missed (\d+)x\)$", line)
        if m:
            checks = [{"date": m[3], "done": False}] * int(m[5])
            state["actions"].append({"id": m[1], "text": m[2], "created": m[3], "meeting_type": m[4],
                                     "status": "open", "checks": list(checks)})
            continue
        m = re.match(r"- \[([\w-]+)\] (.*) \(done ([\d-]*)\)$", line)
        if m:
            state["actions"].append({"id": m[1], "text": m[2], "created": m[3], "meeting_type": "",
                                     "status": "done", "done_date": m[3], "checks": []})
            continue
        m = re.match(r"- (.*) \(([\d-]+)\)$", line)
        if m and section in ("続けること", "Keep doing"):
            state["worked"].append({"text": m[1], "date": m[2]})
    return state


# ---------------------------------------------------------------- redaction


def name_map(transcript: dict, meta: dict, lang: str) -> dict[str, str]:
    labels = load_locale(lang)["labels"]
    me = meta.get("me")
    rels = meta.get("relationships") or {}
    out, counts = {}, {}
    for name in transcript.get("speakers", []):
        if name == me:
            out[name] = labels["me"]
            continue
        role = rels.get(name, "other")
        counts[role] = counts.get(role, 0) + 1
        out[name] = f"{labels['roles'].get(role, labels['roles']['other'])}{counts[role]}"
    # people mentioned by name who were not in the meeting
    for name in meta.get("other_names") or []:
        if isinstance(name, str) and name.strip():
            out[name.strip()] = labels["roles"]["other"]
    # how people are called when it differs from the display name ("Taro Tanaka" -> 田中さん)
    for name, aliases in (meta.get("aliases") or {}).items():
        if name in out:
            for a in aliases if isinstance(aliases, list) else [aliases]:
                if isinstance(a, str) and a.strip():
                    out[a.strip()] = out[name]
    return out


def name_tokens(names) -> set[str]:
    """Lower-case latin parts of names, to keep them out of identifiers."""
    return {t.lower() for n in names for t in re.findall(r"[A-Za-z]{3,}", n)}


_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")


def redact(text: str, names: dict[str, str]) -> str:
    """Best effort name removal.

    Replaces full names, every part (2+ chars) of a spaced name, and a 2-char
    surname guess for unspaced CJK names of 3+ chars. Latin names match
    case-insensitively at word edges. Names never said by a speaker (a third
    person mentioned in passing) cannot be known and are not caught.
    """
    pairs = []
    for name, label in names.items():
        pairs.append((name, label))
        parts = name.split()
        if len(parts) > 1:
            pairs += [(p, label) for p in parts if len(p) >= 2]
        elif len(name) >= 3 and _CJK.fullmatch(name[0]) and all(_CJK.match(c) for c in name):
            pairs.append((name[:2], label))
    for src, dst in sorted(pairs, key=lambda p: -len(p[0])):
        if _CJK.search(src):
            text = text.replace(src, dst)
        else:
            text = re.sub(r"(?<![A-Za-z])" + re.escape(src) + r"(?![A-Za-z])", dst, text, flags=re.I)
    return text


class Sanitizer:
    """Makes free text safe to store: no other participant's words, no names."""

    QUOTED = re.compile(r"[「『“\"]([^」』”\"]{1,200})[」』”\"]")

    def __init__(self, transcript: dict, meta: dict, lang: str, cfg: dict):
        self.me = meta.get("me")
        self.names = name_map(transcript, meta, lang)
        self.redact_names = cfg.get("redact_names", True)
        inferred = bool(transcript.get("speakers_inferred"))
        # with guessed speakers a line marked as ours may be theirs, so treat every line as theirs
        theirs = [u for u in transcript["utterances"] if inferred or not (self.me and u.get("speaker") == self.me)]
        self.their_norm = [normalize((u.get("lead_backchannel") or "") + u["text"]) for u in theirs]
        self.their_raw = "\n".join(u["text"] for u in theirs)
        words = [re.findall(r"[a-z0-9']+", u["text"].lower()) for u in theirs]
        self.their_4grams = {tuple(w[k:k + 4]) for w in words for k in range(len(w) - 3)}
        vocab = []
        for code in ("ja", "en"):
            loc = load_locale(code)
            vocab += loc["hedges"] + loc["backchannels"] + loc["closing_phrases"] + loc.get("stock_phrases", [])
        self.generic = sorted({normalize(v) for v in vocab if normalize(v)}, key=len, reverse=True)

    def _generic(self, text: str) -> bool:
        """Made only of stock phrases such as 「前向きに検討します」: a pattern, not something someone said."""
        rest = normalize(text)
        for g in self.generic:
            rest = rest.replace(g, "")
        return len(rest) <= 1

    def _theirs(self, quoted: str) -> bool:
        q = normalize(quoted)
        if len(q) < 2 or self._generic(quoted):
            return False
        return any(q in t for t in self.their_norm)

    def _drop_cjk_runs(self, text: str, min_len: int = 8) -> str:
        """Remove any stretch of 8+ characters copied verbatim from someone else's line."""
        out, i = [], 0
        while i < len(text):
            hit = 0
            if _CJK.match(text[i]):
                for L in range(min(len(text) - i, 200), min_len - 1, -1):
                    if text[i:i + L] in self.their_raw:
                        hit = L
                        break
            if hit and self._generic(text[i:i + hit]):
                out.append(text[i:i + hit])  # a stock phrase is a pattern, keep it whole
                i += hit
            elif hit:
                out.append("…")
                i += hit
            else:
                out.append(text[i])
                i += 1
        return "".join(out)

    def _drop_word_runs(self, text: str) -> str:
        """Remove any run of 4+ words copied verbatim from someone else's line."""
        spans = [(m.start(), m.end(), m.group(0).lower()) for m in re.finditer(r"[A-Za-z0-9']+", text)]
        marked = [False] * len(spans)
        for k in range(len(spans) - 3):
            if tuple(w for _, _, w in spans[k:k + 4]) in self.their_4grams:
                marked[k:k + 4] = [True] * 4
        out, pos, k = [], 0, 0
        while k < len(spans):
            if marked[k]:
                j = k
                while j + 1 < len(spans) and marked[j + 1]:
                    j += 1
                out.append(text[pos:spans[k][0]] + "…")
                pos, k = spans[j][1], j + 1
            else:
                k += 1
        return "".join(out) + text[pos:]

    def clean(self, text: str) -> str:
        text = self.QUOTED.sub(lambda m: "「…」" if self._theirs(m.group(1)) else m.group(0), text)
        text = self._drop_word_runs(self._drop_cjk_runs(text))
        return redact(text, self.names) if self.redact_names else text


# ---------------------------------------------------------------- save


def own_quote(e, transcript: dict, me) -> bool:
    """True only for a verified quote of an utterance spoken by the user."""
    utts = transcript["utterances"]
    if not me or transcript.get("speakers_inferred") or not isinstance(e, dict) or "quote" not in e:
        return False
    i = e.get("i")
    if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(utts) or utts[i].get("speaker") != me:
        return False
    failures: list = []
    check_item(e, utts, transcript.get("language", "en"), "", failures, [])
    return not failures


def _review_md(judgement, score_res, transcript, meta, lang, san: Sanitizer) -> str:
    me = meta.get("me")
    L = load_locale(lang)["labels"]
    lines = [f"# {meta.get('date', '')} {meta.get('meeting_type', '')} {meta.get('my_position', '') or ''}".rstrip(), ""]
    lines.append(to_markdown(score_res, lang))
    lines.append("## " + ("観点ごとの判定" if lang == "ja" else "Criteria"))
    for c in judgement.get("criteria", []):
        lv = "-" if c.get("level") is None else f"{c['level']}/4"
        # the judge's reason is free text about other people too, so it is not stored
        lines.append(f"- {L['criteria'].get(c['id'], c['id'])} {lv}")
        for e in c.get("evidence") or []:
            if own_quote(e, transcript, me):
                lines.append(f"  - 「{san.clean(e['quote'])}」 (#{e['i']})")
    risks: dict[str, int] = {}
    for s in judgement.get("signals", []):
        if s.get("verdict") == "risk":
            risks[s.get("type", "?")] = risks.get(s.get("type", "?"), 0) + 1
    if risks:
        lines.append("")
        lines.append("## " + ("伝わり度の兆候 (件数のみ)" if lang == "ja" else "Did-it-land signals (counts only)"))
        lines += [f"- {k}: {v}" for k, v in sorted(risks.items())]
    plan = judgement.get("plan_check") or []
    if plan:
        lines.append("")
        lines.append("## " + ("準備との照合" if lang == "ja" else "Against the plan"))
        lines += [f"- [{'x' if p.get('asked') else ' '}] {san.clean(str(p.get('intent', '')))}" for p in plan]
    lines.append("")
    lines.append("## " + ("次回の行動" if lang == "ja" else "Next time"))
    lines += [f"- [ ] {san.clean(a['text'])}" for a in judgement.get("next_actions", [])]
    return "\n".join(lines) + "\n"


def save(judgement, score_res, transcript, meta, cfg, root: Path) -> dict:
    lang = meta.get("language") or transcript.get("language") or "en"
    date = _check_date(meta.get("date") or dt.date.today().isoformat())
    if meta.get("prep_id") is not None and not (isinstance(meta["prep_id"], str) and PREP_ID.fullmatch(meta["prep_id"])):
        raise ValueError(f"prep_id must look like P-YYYYMMDD-n, got {meta['prep_id']!r}")
    state = load_state(root)
    san = Sanitizer(transcript, meta, lang, cfg)
    warnings = []

    by_id = {a["id"]: a for a in state["actions"]}
    for chk in judgement.get("previous_actions_check", []):
        a = by_id.get(chk.get("id"))
        if a is None:
            warnings.append(f"unknown action id {chk.get('id')!r}")
            continue
        if chk.get("done") is None:
            # recorded so "not applicable this time" differs from "never checked"
            a["checks"].append({"date": date, "done": None, "note": san.clean(str(chk.get("note") or "not applicable"))})
            continue
        a["checks"].append({"date": date, "done": bool(chk["done"])})
        if chk["done"]:
            a["status"], a["done_date"] = "done", date

    prefix = "A-" + date.replace("-", "")
    n = sum(1 for a in state["actions"] if a["id"].startswith(prefix))
    new_ids = []
    for act in judgement.get("next_actions", []):
        n += 1
        aid = f"{prefix}-{n}"
        state["actions"].append({"id": aid, "text": san.clean(act["text"]), "created": date,
                                 "meeting_type": score_res.get("rubric", meta.get("meeting_type", "")),
                                 "status": "open", "checks": []})
        new_ids.append(aid)

    banned = name_tokens(san.names)
    for h in judgement.get("habits", []):
        hid = h.get("id", "")
        if not HABIT_ID.fullmatch(hid) or any(t in hid for t in banned):
            warnings.append(f"habit id {hid!r} is not a generic snake_case id; stored as 'unlabelled'")
            hid = "unlabelled"
        rec = state["habits"].setdefault(hid, {"label": san.clean(h.get("label") or hid), "count": 0, "first_seen": date})
        rec["count"] += 1
        # reviews can be added out of order (an older meeting reviewed later)
        rec["first_seen"] = min(rec.get("first_seen") or date, date)
        rec["last_seen"] = max(rec.get("last_seen") or date, date)
    known = {w["text"] for w in state["worked"]}
    for w in judgement.get("worked", []):
        w = san.clean(w)
        if w not in known:
            known.add(w)
            state["worked"].append({"text": w, "date": date})

    reviews = root / "reviews"
    reviews.mkdir(parents=True, exist_ok=True)
    base = f"{date}_{meta.get('meeting_type') if meta.get('meeting_type') in TYPES else 'meeting'}"
    path, k = reviews / f"{base}.md", 1
    while path.exists():
        k += 1
        path = reviews / f"{base}_{k}.md"
    path.write_text(_review_md(judgement, score_res, transcript, meta, lang, san), encoding="utf-8")

    plan = judgement.get("plan_check") or []
    prep_id = meta.get("prep_id")
    planned = None
    if prep_id:
        pf = root / "prep" / f"{prep_id}.json"
        if pf.is_file():
            rec = read_json(pf)
            planned = len(rec.get("intents", []))
            if planned != len(plan):
                warnings.append(f"plan has {planned} aims but plan_check has {len(plan)}; coverage uses the plan's count")
            rec["reviewed"], rec["review"] = True, path.name
            write_json(rec, pf)
        else:
            warnings.append(f"prep {prep_id!r} not found")

    record = {
        "date": date,
        "prep_id": prep_id,
        "plan_coverage": (round(sum(1 for p in plan if p.get("asked")) / (planned or len(plan)), 2)
                          if (planned or plan) else None),
        "rubric": score_res.get("rubric"),
        "meeting_score": score_res["meeting"]["score"],
        "self_score": score_res["self"]["score"],
        "meeting_band": score_res["meeting"]["band"],
        "self_band": score_res["self"]["band"],
        "coverage": {t: score_res[t]["coverage"] for t in ("meeting", "self")},
        "overrun_ratio": score_res.get("overrun_ratio"),
        "levels": {c["id"]: c.get("level") for c in judgement.get("criteria", [])},
        "habits": [h.get("id") if HABIT_ID.fullmatch(h.get("id", "")) and not any(t in h.get("id", "") for t in banned)
                   else "unlabelled" for h in judgement.get("habits", [])],
        "source": transcript.get("source"),
    }
    with open(root / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    save_state(root, state, lang)
    return {"review": str(path), "new_action_ids": new_ids, "warnings": warnings,
            "learnings": str(root / "learnings.md")}


# ---------------------------------------------------------------- prepare mode


def summary(state: dict, limit: int = 5) -> dict:
    habits = sorted(state["habits"].items(), key=lambda kv: (-kv[1]["count"], kv[0]))[:limit]
    return {
        "habits": [{"id": k, "label": v["label"], "count": v["count"], "last_seen": v["last_seen"]} for k, v in habits],
        "open_actions": [{k: a[k] for k in ("id", "text", "created", "meeting_type")}
                         for a in state["actions"] if a["status"] == "open"],
    }


def prep_save(prep: dict, cfg: dict, root: Path) -> dict:
    """Keep only what the review needs: type, goal, length, focus and question aims.

    `counterpart_names` is used to scrub names from the goal and aims, then dropped.
    Profile text and research notes are never passed in or stored.
    """
    lang = prep.get("language") or "ja"
    labels = load_locale(lang)["labels"]
    role = labels["roles"].get(prep.get("counterpart_role") or "other", labels["roles"]["other"])
    names = {n: f"{role}1" for n in prep.get("counterpart_names", []) if n}
    clean = (lambda t: redact(t, names)) if cfg.get("redact_names", True) else (lambda t: t)
    date = _check_date(prep.get("date") or dt.date.today().isoformat())
    if prep.get("meeting_type") not in TYPES:
        raise ValueError(f"meeting_type must be one of {TYPES}, got {prep.get('meeting_type')!r}")
    folder = root / "prep"
    folder.mkdir(parents=True, exist_ok=True)
    n = len(list(folder.glob(f"P-{date.replace('-', '')}-*.json"))) + 1
    rec = {
        "id": f"P-{date.replace('-', '')}-{n}",
        "date": date,
        "language": lang,
        "meeting_type": prep.get("meeting_type"),
        "my_position": prep.get("my_position"),
        "stage": prep.get("stage"),
        "scheduled_minutes": prep.get("scheduled_minutes"),
        "goal": clean(prep.get("goal") or ""),
        "focus_action_ids": prep.get("focus_action_ids", []),
        "intents": [clean(i) for i in prep.get("intents", [])],
        "reviewed": False,
    }
    write_json(rec, folder / f"{rec['id']}.json")
    save_state(root, load_state(root), lang)
    return rec


def prep_find(root: Path, date: str | None = None) -> dict | None:
    """The unreviewed plan for that date, else the latest unreviewed plan from the 3 days before it."""
    folder = root / "prep"
    if not folder.is_dir():
        return None
    preps = [read_json(p) for p in sorted(folder.glob("P-*.json"))]
    preps = [p for p in preps if not p.get("reviewed")]
    if not preps:
        return None
    if not date:
        return preps[-1]
    same = [p for p in preps if p["date"] == date]
    if same:
        return same[-1]
    d = dt.date.fromisoformat(date)
    near = [p for p in preps if 0 < (d - dt.date.fromisoformat(p["date"])).days <= 3]
    return near[-1] if near else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["open-actions", "save", "export", "import", "summary", "prep-save", "prep-find", "config"])
    ap.add_argument("block", nargs="?", help="for import: file with a pasted learnings block")
    ap.add_argument("--store")
    ap.add_argument("--config")
    ap.add_argument("--judgement")
    ap.add_argument("--score")
    ap.add_argument("--transcript")
    ap.add_argument("--meta")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--prep")
    ap.add_argument("--date")
    a = ap.parse_args(argv)
    cfg = load_config(a.config, a.store)
    root = store_dir(cfg, a.store)
    if a.command == "open-actions":
        state = load_state(root)
        write_json([{k: x[k] for k in ("id", "text", "created", "meeting_type")} | {"checks": len(x["checks"])}
                    for x in state["actions"] if x["status"] == "open"])
    elif a.command == "summary":
        write_json(summary(load_state(root)))
    elif a.command == "prep-save":
        if not a.prep:
            ap.error("prep-save needs --prep")
        try:
            write_json(prep_save(read_json(a.prep), cfg, root))
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    elif a.command == "prep-find":
        write_json(prep_find(root, a.date))
    elif a.command == "export":
        print(render(load_state(root), a.lang, open_preps(root)))
    elif a.command == "config":
        write_json({k: cfg.get(k) for k in ("store_dir", "org_pack", "notes_dirs", "research_budget", "redact_names")}
                   | {"store_used": str(root)})
    elif a.command == "import":
        if not a.block:
            ap.error("import needs a file containing the pasted block")
        state = parse_block(Path(a.block).read_text(encoding="utf-8"))
        preps = state.pop("preps", [])
        (root / "prep").mkdir(parents=True, exist_ok=True)
        for pr in preps:
            write_json(pr, root / "prep" / f"{pr['id']}.json")
        save_state(root, state, a.lang)
        print(f"imported {len(state['actions'])} actions, {len(state['habits'])} habits, {len(preps)} plans into {root}")
    else:
        for k in ("judgement", "score", "transcript", "meta"):
            if not getattr(a, k):
                ap.error(f"save needs --{k}")
        try:
            res = save(read_json(a.judgement), read_json(a.score), read_json(a.transcript), read_json(a.meta), cfg, root)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        write_json(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
