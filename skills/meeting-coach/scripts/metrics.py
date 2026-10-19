#!/usr/bin/env python3
"""Machine measurements for a parsed transcript.

Everything here is a candidate signal for the judge, not a verdict: a hedge
followed by an owner and a date is fine, a short "はい" can be real agreement.

Usage:
  python3 metrics.py transcript.json [--meta meta.json] [--config cfg.json] [-o metrics.json]
"""
from __future__ import annotations

import argparse
import sys

sys.dont_write_bytecode = True  # keep the skill folder clean

from common import (
    count_fillers,
    find_phrases,
    is_question,
    load_config,
    load_locale,
    matches_any,
    read_json,
    split_sentences,
    units,
    write_json,
)


def _questions(text: str, locale: dict) -> list[str]:
    return [s for s in split_sentences(text, locale["language"]) if is_question(s, locale)]


def duration_info(transcript: dict, meta: dict) -> dict:
    actual, source = transcript.get("duration_sec"), transcript.get("duration_source")
    if meta.get("actual_minutes"):
        actual, source = float(meta["actual_minutes"]) * 60, "meta"
    scheduled = float(meta["scheduled_minutes"]) * 60 if meta.get("scheduled_minutes") else None
    if scheduled is not None and scheduled <= 0:
        scheduled = None  # score.py reports the bad value
    overrun = None
    if actual is not None and actual >= 0 and scheduled:
        overrun = (actual - scheduled) / scheduled  # unrounded: tiers compare against exact values
    return {
        "actual_sec": actual,
        "source": source,
        "actual_is_lower_bound": source == "last_timestamp",
        "scheduled_sec": scheduled,
        "overrun_ratio": overrun,
    }


def compute(transcript: dict, meta: dict, cfg: dict) -> dict:
    lang = transcript["language"]
    loc = load_locale(lang)
    utts = transcript["utterances"]
    me = meta.get("me")
    unavailable: dict[str, str] = {}
    if not transcript["has_speakers"]:
        for k in ("talk_share", "my_long_turns", "thin_responses", "speakers", "silences_after_my_questions"):
            unavailable[k] = "no speaker labels in transcript"
    elif not me:
        unavailable["my_metrics"] = "which speaker is me is unknown"
    elif me not in transcript["speakers"]:
        unavailable["my_metrics"] = f"speaker {me!r} not found in transcript"
        me = None

    # ---- per speaker
    speakers: dict[str, dict] = {}
    for u in utts:
        key = u["speaker"] or "_unknown"
        d = speakers.setdefault(key, {
            "units": 0, "backchannel_units": 0, "turns": 0, "backchannel_only_turns": 0,
            "questions": 0, "fillers": 0, "longest_turn_units": 0, "longest_turn_i": None,
        })
        content = 0 if u["backchannel_only"] else units(u["text"], lang)
        d["units"] += content
        d["backchannel_units"] += units(u["lead_backchannel"], lang) + (units(u["text"], lang) if u["backchannel_only"] else 0)
        d["turns"] += 1
        d["backchannel_only_turns"] += int(u["backchannel_only"])
        if not u["backchannel_only"]:
            d["questions"] += len(_questions(u["text"], loc))
        d["fillers"] += count_fillers(u["text"], loc)
        if content > d["longest_turn_units"]:
            d["longest_turn_units"], d["longest_turn_i"] = content, u["i"]
    total = sum(d["units"] for d in speakers.values()) or 1
    for d in speakers.values():
        d["share"] = round(d["units"] / total, 3)

    out: dict = {
        "version": 1,
        "language": lang,
        "unit": loc["unit"],
        "me": me,
        "quality": {
            k: transcript.get(k)
            for k in ("source", "has_speakers", "has_timestamps", "timestamp_granularity", "fillers_preserved")
        } | {"removed_asr_lines": len(transcript.get("removed", [])),
             "suspect_asr_utterances": [u["i"] for u in utts if u.get("suspect_asr")],
             "gaps": transcript.get("gaps", []),
             "speakers_inferred": bool(transcript.get("speakers_inferred"))},
        "unavailable": unavailable,
        "duration": duration_info(transcript, meta),
        "speakers": speakers if transcript["has_speakers"] else {},
    }

    # ---- hedges (any speaker) and whether an owner/date follows
    window = int(cfg["hedge_followup_window"])
    hedges = []
    for u in utts:
        for phrase in find_phrases(u["text"], loc["hedges"]):
            follow = utts[u["i"]: u["i"] + window + 1]
            hedges.append({
                "i": u["i"], "speaker": u["speaker"], "by_me": bool(me) and u["speaker"] == me, "phrase": phrase,
                "followed_by_commitment": any(matches_any(x["text"], loc["deadline_patterns"]) for x in follow),
                "owner_nearby": any(matches_any(x["text"], loc["owner_patterns"]) for x in follow),
            })
    out["hedge_candidates"] = hedges

    # ---- closing
    # the closing stretch: the last fifth of the meeting (at least 3 turns, at most closing_window)
    cw = min(int(cfg["closing_window"]), max(3, round(len(utts) * 0.2)))
    tail = utts[-cw:]
    deadline_at = [x["i"] for x in tail if matches_any(x["text"], loc["deadline_patterns"])]
    out["closing"] = {
        "range": [tail[0]["i"], tail[-1]["i"]] if tail else None,
        "deadline_utterances": deadline_at,
        "owner_utterances": [x["i"] for x in tail if matches_any(x["text"], loc["owner_patterns"])],
        "closing_phrase_only": bool(tail) and not deadline_at
        and any(find_phrases(x["text"], loc["closing_phrases"]) for x in tail),
    }

    if not transcript["has_speakers"] or not me:
        return out

    # ---- my turns: runs of my utterances, absorbing listeners' pure backchannels
    long_units = int(cfg["long_turn_units"].get(lang, 150))
    thin_units = int(cfg["thin_response_units"].get(lang, 8))
    runs, i = [], 0
    while i < len(utts):
        if utts[i]["speaker"] != me:
            i += 1
            continue
        j, my_units, nods = i, 0, 0
        while j < len(utts) and (utts[j]["speaker"] == me or utts[j]["backchannel_only"]):
            if utts[j]["speaker"] == me:
                my_units += 0 if utts[j]["backchannel_only"] else units(utts[j]["text"], lang)
            else:
                nods += 1
            j += 1
        runs.append({"from": i, "to": j - 1, "units": my_units, "listener_backchannels": nods,
                     "response_i": j if j < len(utts) else None})
        i = j

    def _span(r):
        a, b = utts[r["from"]], utts[r["to"]]
        if a.get("start") is not None and b.get("end") is not None:
            return round(b["end"] - a["start"], 1)
        return None

    out["my_long_turns"] = [
        {"from": r["from"], "to": r["to"], "units": r["units"], "approx_sec": _span(r),
         "listener_backchannels": r["listener_backchannels"]}
        for r in runs if r["units"] >= long_units
    ]
    thin = []
    for r in runs:
        if r["units"] < long_units or r["response_i"] is None:
            continue
        resp = utts[r["response_i"]]
        n = units(resp["text"], lang)
        if n < thin_units and not _questions(resp["text"], loc):
            thin.append({"after_turn": [r["from"], r["to"]], "response_i": resp["i"], "speaker": resp["speaker"], "units": n})
    out["thin_responses"] = thin

    mine = [u for u in utts if u["speaker"] == me and not u["backchannel_only"]]
    stacked, continued = [], []
    min_q = 6 if lang == "ja" else 3  # 「8人か」「本当ですか?」 are reactions, not questions put to someone
    for u in mine:
        sents = split_sentences(u["text"], lang)
        qidx = [k for k, s in enumerate(sents) if is_question(s, loc) and units(s, lang) >= min_q]
        if len(qidx) >= 2:
            stacked.append({"i": u["i"], "questions": len(qidx)})
        after = [s for s in sents[qidx[0] + 1:] if not is_question(s, loc)] if qidx else []
        if len(after) >= 2:
            continued.append({"i": u["i"], "statements_after_question": len(after)})
    out["my_stacked_questions"] = stacked
    out["my_question_then_kept_talking"] = continued
    out["my_share"] = speakers.get(me, {}).get("share")
    out["counterpart_questions"] = sum(d["questions"] for s, d in speakers.items() if s != me)
    out["my_questions"] = speakers.get(me, {}).get("questions", 0)

    # ---- silences after my questions (only with real per-utterance timing)
    gran = transcript.get("timestamp_granularity")
    if gran in ("utterance", "word") and not any(u.get("time_estimated") for u in utts):
        gap_min = float(cfg["silence_after_question_sec"])
        sil = []
        for u in mine:
            nxt = utts[u["i"] + 1] if u["i"] + 1 < len(utts) else None
            if nxt and _questions(u["text"], loc) and u.get("end") is not None and nxt.get("start") is not None:
                gap = nxt["start"] - u["end"]
                if gap >= gap_min:
                    sil.append({"i": u["i"], "gap_sec": round(gap, 1)})
        out["silences_after_my_questions"] = sil
    else:
        out["unavailable"]["silences_after_my_questions"] = "needs per-utterance timestamps (VTT or audio)"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcript")
    ap.add_argument("--meta")
    ap.add_argument("--config")
    ap.add_argument("-o", "--out")
    a = ap.parse_args(argv)
    t = read_json(a.transcript)
    meta = read_json(a.meta) if a.meta else {}
    m = compute(t, meta, load_config(a.config))
    write_json(m, a.out)
    d = m["duration"]
    print(
        f"me={m['me']} my_share={m.get('my_share')} overrun={d['overrun_ratio']} "
        f"long_turns={len(m.get('my_long_turns', []))} thin={len(m.get('thin_responses', []))} "
        f"hedges={len(m['hedge_candidates'])} unavailable={list(m['unavailable'])}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
