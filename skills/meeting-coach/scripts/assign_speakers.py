#!/usr/bin/env python3
"""Give speakers to a transcript that has none, from the judge's reading of context.

Many automatic transcripts (Whisper, some meeting tools) carry no speaker
labels. The judge can often tell who is talking from content (who explains,
who asks). This writes those assignments into the transcript and marks it
`speakers_inferred`, so every later step and the report treat speaker-based
results as estimates.

assignments.json:
  {"ranges": [[32, 38, "Aki"], [39, 39, "Me"], ...],   # inclusive utterance ranges
   "drop":   [[0, 31, "notes pasted above the transcript"]]}   # optional

Usage:
  python3 assign_speakers.py transcript.json assignments.json -o transcript.json
"""
from __future__ import annotations

import argparse
import sys

sys.dont_write_bytecode = True  # keep the skill folder clean

from common import read_json, write_json


def assign(transcript: dict, spec: dict) -> dict:
    utts = transcript["utterances"]
    n = len(utts)
    errors = []

    def _range(r, k, what):
        if not (isinstance(r, list) and len(r) >= 2 and all(isinstance(x, int) for x in r[:2]) and 0 <= r[0] <= r[1] < n):
            errors.append(f"{what}[{k}]: needs [from, to, ...] within 0..{n - 1}, got {r!r}")
            return None
        return r

    dropped = set()
    for k, r in enumerate(spec.get("drop", [])):
        if _range(r, k, "drop"):
            dropped.update(range(r[0], r[1] + 1))
    seen = set()
    for k, r in enumerate(spec.get("ranges", [])):
        if not _range(r, k, "ranges"):
            continue
        if len(r) < 3 or not isinstance(r[2], str) or not r[2].strip():
            errors.append(f"ranges[{k}]: third item must be a speaker name")
            continue
        for i in range(r[0], r[1] + 1):
            if i in seen:
                errors.append(f"utterance {i} assigned twice")
            seen.add(i)
            utts[i]["speaker"] = r[2].strip()
    if errors:
        return {"errors": errors}

    kept = [u for u in utts if u["i"] not in dropped]
    for new_i, u in enumerate(kept):
        u["i"] = new_i
    order = []
    for u in kept:
        if u["speaker"] and u["speaker"] not in order:
            order.append(u["speaker"])
    out = dict(transcript)
    out["utterances"] = kept
    out["speakers"] = order
    out["has_speakers"] = len(order) >= 2
    out["speakers_inferred"] = True
    out["dropped"] = [{"from": r[0], "to": r[1], "reason": r[2] if len(r) > 2 else ""} for r in spec.get("drop", [])]
    out["unassigned"] = [u["i"] for u in kept if not u["speaker"]]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcript")
    ap.add_argument("assignments")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args(argv)
    res = assign(read_json(a.transcript), read_json(a.assignments))
    if res.get("errors"):
        write_json(res)
        return 2
    write_json(res, a.out)
    print(f"speakers={res['speakers']} utterances={len(res['utterances'])} unassigned={len(res['unassigned'])} "
          f"(speakers are inferred)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
