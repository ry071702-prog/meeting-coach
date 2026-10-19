#!/usr/bin/env python3
"""Turn the judge's criterion levels into scores, deterministically.

The judge (the LLM) only assigns a level 0-4 with evidence to each criterion.
Points, the time penalty and bands come from config, so the same levels always
give the same score. A criterion with level null is "not scorable" and is
dropped from the denominator instead of counting as zero.

Usage:
  python3 score.py judgement.json --meta meta.json [--metrics metrics.json]
                   [--config cfg.json] [-o score.json] [--md]
"""
from __future__ import annotations

import argparse
import sys
from decimal import ROUND_HALF_UP, Decimal

sys.dont_write_bytecode = True  # keep the skill folder clean

from common import load_config, load_locale, read_json, write_json

TRACKS = ("meeting", "self")


def rubric_key(meta: dict) -> str:
    t = meta.get("meeting_type") or "meeting"
    if t == "one-on-one":
        return f"one-on-one/{meta.get('my_position') or 'peer'}"
    return t


def time_penalty(overrun, cfg: dict):
    if overrun is None:
        return None
    for tier in cfg["time_penalty"]["tiers"]:
        if tier["max_overrun"] is None or overrun <= tier["max_overrun"]:
            return tier["points"]
    return None


def band_of(score, cfg: dict):
    if score is None:
        return None
    for b in sorted(cfg["bands"], key=lambda b: -b["min"]):
        if score >= b["min"]:
            return b["id"]
    return None


def round_half_up(x: float) -> int:
    """62.5 -> 63 (Python's round() would give 62)."""
    # round away float noise first so 57.49999999999999 counts as 57.5
    return int(Decimal(str(round(x, 6))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _overrun(meta: dict, metrics: dict | None, errors: list):
    """Overrun ratio, unrounded. A length the user typed into meta wins over the measured one."""
    sched, actual = meta.get("scheduled_minutes"), meta.get("actual_minutes")
    if sched is not None and float(sched) <= 0:
        errors.append(f"scheduled_minutes must be > 0, got {sched!r}")
        return None
    if actual is not None and float(actual) < 0:
        errors.append(f"actual_minutes must be >= 0, got {actual!r}")
        return None
    if actual is not None and sched:
        return (float(actual) - float(sched)) / float(sched)
    if metrics and metrics.get("duration", {}).get("overrun_ratio") is not None:
        return metrics["duration"]["overrun_ratio"]
    return None


def compute(judgement: dict, meta: dict, metrics: dict | None, cfg: dict) -> dict:
    if meta.get("meeting_type") == "one-on-one" and meta.get("my_position") not in ("report", "manager", "peer"):
        return {"errors": [f"one-on-one needs my_position report|manager|peer, got {meta.get('my_position')!r}"]}
    key = rubric_key(meta)
    if key not in cfg["rubrics"]:
        return {"errors": [f"no rubric {key!r} in config (meeting_type / my_position)"]}
    rub = cfg["rubrics"][key]
    errors, warnings, levels = [], [], {}
    for c in judgement.get("criteria", []):
        cid = c.get("id") if isinstance(c, dict) else None
        if not isinstance(cid, str) or not cid:
            errors.append(f"criterion without an id: {c!r}"[:120])
            continue
        if cid in levels:
            errors.append(f"{cid}: judged twice")
            continue
        lv = c.get("level")
        if lv is not None and (isinstance(lv, bool) or not isinstance(lv, int) or not 0 <= lv <= 4):
            errors.append(f"{cid}: level must be an integer 0-4 or null, got {lv!r}")
            continue
        levels[cid] = lv
    known = set(rub["meeting"]) | set(rub["self"])
    for cid in sorted(set(levels) - known):
        errors.append(f"{cid}: not a criterion of rubric {key!r}")
    for cid in sorted(known - set(levels)):
        warnings.append(f"{cid}: not judged, treated as not scorable")

    overrun = _overrun(meta, metrics, errors)
    pen = time_penalty(overrun, cfg)
    fac = meta.get("facilitator")
    facilitator_is_me = fac is not None and fac in ("me", meta.get("me"))
    only_when_fac = cfg["time_penalty"]["apply_to_self_only_when_facilitator"]

    inferred = bool(metrics and metrics.get("quality", {}).get("speakers_inferred"))
    result = {"rubric": key, "overrun_ratio": overrun, "time_penalty_points": pen, "speakers_inferred": inferred,
              "facilitator_is_me": facilitator_is_me, "warnings": warnings, "errors": errors}
    for track in TRACKS:
        weights = rub[track]
        rows, got, possible = [], 0.0, 0
        for cid, w in weights.items():
            lv = levels.get(cid)
            pts = None if lv is None else w * lv / 4
            if pts is not None:
                got += pts
                possible += w
            rows.append({"id": cid, "weight": w, "level": lv, "points": None if pts is None else round(pts, 2)})
        total_w = sum(weights.values())
        coverage = possible / total_w if total_w else 0
        raw = got * 100 / possible if possible else None  # multiply first: 57.5/100*100 is 57.4999...
        penalties = []
        if pen and (track == "meeting" or facilitator_is_me or not only_when_fac):
            penalties.append({"reason": "time_overrun", "points": pen, "overrun_ratio": overrun})
        final = None if raw is None else max(0, min(100, round_half_up(raw - sum(p["points"] for p in penalties))))
        result[track] = {
            "score": final,
            "band": band_of(final, cfg),
            "coverage": round(coverage, 2),
            "low_confidence": coverage < cfg["min_coverage"] or (inferred and track == "self"),
            "breakdown": rows,
            "penalties": penalties,
        }
    return result


def to_markdown(res: dict, lang: str) -> str:
    L = load_locale(lang)["labels"]
    lines = []
    for track in TRACKS:
        t = res[track]
        head = f"### {L[track]}: "
        head += f"{t['score']} ({t['band']} {L['bands'].get(t['band'], '')})" if t["score"] is not None else L["not_scorable"]
        lines.append(head)
        note = L["speakers_inferred"] if res.get("speakers_inferred") and track == "self" else L["low_confidence"]
        lines.append(f"{L['coverage']} {round(t['coverage'] * 100)}%" + (f" / {note}" if t["low_confidence"] else ""))
        for p in t["penalties"]:
            lines.append(f"{L['time_penalty']} {round_half_up(p['overrun_ratio'] * 100):+d}% → -{p['points']}")
        if track == "self" and res["time_penalty_points"] and not t["penalties"]:
            lines.append(L["time_penalty_not_applied"])
        lines.append("")
        lines.append(f"| | {L['weight']} | {L['level']} | {L['points']} |")
        lines.append("|---|---:|---:|---:|")
        for r in t["breakdown"]:
            name = L["criteria"].get(r["id"], r["id"])
            lv = "-" if r["level"] is None else f"{r['level']}/4"
            pts = L["not_scorable"] if r["points"] is None else f"{r['points']:g}"
            lines.append(f"| {name} | {r['weight']} | {lv} | {pts} |")
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("judgement")
    ap.add_argument("--meta", required=True)
    ap.add_argument("--metrics")
    ap.add_argument("--config")
    ap.add_argument("-o", "--out")
    ap.add_argument("--md", action="store_true", help="print a markdown score table to stdout")
    a = ap.parse_args(argv)
    meta = read_json(a.meta)
    metrics = read_json(a.metrics) if a.metrics else None
    res = compute(read_json(a.judgement), meta, metrics, load_config(a.config))
    if res.get("errors"):
        write_json(res)
        return 2
    if a.out:
        write_json(res, a.out)
    lang = meta.get("language") or (metrics or {}).get("language") or "en"
    if a.md:
        print(to_markdown(res, lang))
    elif not a.out:
        write_json(res)
    for w in res["warnings"]:
        print("warning:", w, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
