#!/usr/bin/env python3
"""Check that every quote the judge cites really is in the transcript.

A quote must appear (after normalising whitespace and punctuation) in the cited
utterance itself. Long quotes may be shortened with "…"; each piece must then
appear in order, be long enough to mean something, and not skip a negation. An "absence" item (something that should
have been said but wasn't) must point at a valid utterance range instead.

Exit 0 when every check passes (warnings allowed), 1 otherwise.

Usage:
  python3 verify_evidence.py judgement.json transcript.json
"""
from __future__ import annotations

import argparse
import re
import sys

sys.dont_write_bytecode = True  # keep the skill folder clean

import unicodedata

from common import normalize, read_json, write_json

ELLIPSIS = re.compile(r"…+|\.\.\.+|‥+")
NEGATION = {
    "ja": re.compile(r"ない|なかった|ません|無い|ではな|じゃな|いいえ"),
    "en": re.compile(r"\b(not|never|no|none|nobody|nothing|cannot|without)\b|n't\b"),
}
# a quote cut with "…" must keep enough of each piece to be meaningful
MIN_PIECE = {"ja": 4, "en": 2}  # characters for ja, words for en
_EN_PUNCT = re.compile(r"[^\w'\s]+")


def _norm(text: str, lang: str) -> str:
    """ja: no spaces or punctuation. en: words separated by single spaces, padded so matches stop at word edges."""
    if lang == "ja":
        return normalize(text)
    words = _EN_PUNCT.sub(" ", unicodedata.normalize("NFKC", text).lower()).split()
    return " " + " ".join(words) + " "


def _size(piece: str, lang: str) -> int:
    return len(piece) if lang == "ja" else len(piece.split())


def _full(u: dict, lang: str) -> str:
    return _norm((u.get("lead_backchannel") or "") + " " + (u.get("text") or ""), lang)


def _match(hay: str, pieces: list[str], lang: str):
    """Spans of the pieces found in order, or None."""
    pos, spans = 0, []
    for p in pieces:
        needle = p if lang == "ja" else " " + p.strip() + " "
        k = hay.find(needle, pos)
        if k < 0:
            return None
        spans.append((k, k + len(needle)))
        pos = k + len(needle) - (0 if lang == "ja" else 1)
    return spans


def check_item(item, utts: list[dict], lang: str, where: str, failures: list, warnings: list) -> None:
    n = len(utts)
    if not isinstance(item, dict):
        failures.append(f"{where}: expected an object with i/quote or absence/range, got {type(item).__name__}")
        return
    if "absence" in item:
        if not str(item.get("absence") or "").strip():
            failures.append(f"{where}: absence needs a description of what was missing")
        rng = item.get("range")
        if not (isinstance(rng, list) and len(rng) == 2 and all(isinstance(x, int) for x in rng)
                and 0 <= rng[0] <= rng[1] < n):
            failures.append(f"{where}: absence needs a valid range [a, b] within 0..{n - 1}, got {rng!r}")
        return
    i, quote = item.get("i"), item.get("quote")
    if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < n:
        failures.append(f"{where}: utterance index {i!r} out of range 0..{n - 1}")
        return
    if not quote or not isinstance(quote, str):
        failures.append(f"{where}: missing quote")
        return
    raw = [p for p in ELLIPSIS.split(quote)]
    pieces = [_norm(p, lang).strip() if lang != "ja" else _norm(p, lang) for p in raw]
    pieces = [p for p in pieces if p]
    if not pieces:
        failures.append(f"{where}: quote {quote!r} is empty after normalisation")
        return
    floor = MIN_PIECE.get(lang, 2) if len(pieces) > 1 else (2 if lang == "ja" else 1)
    if any(_size(p, lang) < floor for p in pieces):
        failures.append(f"{where}: quote {quote[:40]!r} is too short to be evidence; quote a longer stretch")
        return
    spans = _match(_full(utts[i], lang), pieces, lang)
    if spans is None:
        elsewhere = [u["i"] for u in utts if _match(_full(u, lang), pieces, lang) is not None]
        if elsewhere:
            failures.append(f"{where}: quote is not in utterance {i}; it is in i={elsewhere[:5]}")
        else:
            failures.append(f"{where}: quote {quote[:40]!r} not found in transcript (copy it verbatim)")
        return
    hay = _full(utts[i], lang)
    neg = NEGATION.get(lang, NEGATION["en"])
    for (_, a_end), (b_start, _) in zip(spans, spans[1:]):
        if neg.search(hay[a_end:b_start]):
            failures.append(f"{where}: the part cut with … contains a negation; quote it in full")
            return
    if utts[i].get("suspect_asr"):
        warnings.append(f"{where}: quote comes from utterance {i}, flagged as a possible transcription error")
    spk = item.get("speaker")
    if spk and utts[i].get("speaker") and spk != utts[i]["speaker"]:
        failures.append(f"{where}: quote is said by {utts[i]['speaker']!r}, not {spk!r}")


def verify(judgement: dict, transcript: dict) -> dict:
    utts = transcript["utterances"]
    lang = transcript.get("language", "en")
    failures: list[str] = []
    warnings: list[str] = []

    def check(item, where):
        check_item(item, utts, lang, where, failures, warnings)

    for c in judgement.get("criteria", []):
        if not isinstance(c, dict):
            failures.append(f"criteria: expected objects, got {type(c).__name__}")
            continue
        ev = c.get("evidence") or []
        if c.get("level") is not None and not ev:
            failures.append(f"criteria.{c.get('id')}: a scored criterion needs at least one evidence item")
        for k, item in enumerate(ev):
            check(item, f"criteria.{c.get('id')}.evidence[{k}]")
    for k, sig in enumerate(judgement.get("signals", [])):
        check(sig, f"signals[{k}]" + (f"({sig.get('type')})" if isinstance(sig, dict) else ""))
    for k, entry in enumerate(judgement.get("plan_check", [])):
        if isinstance(entry, dict) and isinstance(entry.get("asked"), bool):
            kinds = {"absence" if isinstance(e, dict) and "absence" in e else "quote" for e in entry.get("evidence") or []}
            need = "quote" if entry["asked"] else "absence"
            if need not in kinds:
                failures.append(f"plan_check[{k}]: asked={entry['asked']} needs a{'' if need == 'quote' else 'n'} {need} item")
    for section in ("strengths", "improvements", "previous_actions_check", "plan_check"):
        for k, entry in enumerate(judgement.get(section, [])):
            if not isinstance(entry, dict):
                failures.append(f"{section}[{k}]: expected an object")
                continue
            for m, item in enumerate(entry.get("evidence") or []):
                check(item, f"{section}[{k}].evidence[{m}]")
    return {"ok": not failures, "failures": failures, "warnings": warnings}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("judgement")
    ap.add_argument("transcript")
    a = ap.parse_args(argv)
    res = verify(read_json(a.judgement), read_json(a.transcript))
    write_json(res)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
