#!/usr/bin/env python3
"""Parse a meeting transcript into the common JSON used by meeting-coach.

Formats: Google Meet (Gemini notes) transcript, WebVTT (Zoom / Teams),
Otter-style "Name  0:05" blocks, plain "Name: text" lines (optionally prefixed
with [hh:mm:ss]), and lines with no speaker at all.

Usage:
  python3 parse_transcript.py INPUT|- [-o transcript.json] [--lang ja|en]
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True  # keep the skill folder clean

from common import (
    backchannel_token_matcher,
    count_fillers,
    detect_language,
    hms_to_sec,
    load_config,
    load_locale,
    normalize,
    tokens,
    units,
    write_json,
)

TS_LINE = re.compile(r"^\s*(\d{1,2}:\d{2}:\d{2})\s*$")
VTT_TIME = re.compile(
    r"^\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{3})\s*-->\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{3})"
)
_TS = r"((?:\d{1,2}:)?\d{1,2}:\d{2})(?:[.,]\d+)?"
# "[00:01:02] text", "(1:02)text", or a bare "00:01:02 text" (bare needs a space after it)
TS_PREFIX = re.compile(r"^\s*(?:[\[(]" + _TS + r"[\])]\s*|" + _TS + r"\s+)")
SPEAKER = re.compile(r"^(?P<name>[^:：\n]{1,40}?)\s*[:：](?!//)\s*(?P<text>.*)$")
OTTER_HEAD = re.compile(r"^(?P<name>\S.{0,39}?)\s{2,}(?P<ts>(?:\d{1,2}:)?\d{1,2}:\d{2})\s*$")
DATE_ONLY = re.compile(r"^\s*(\d{4}年\d{1,2}月\d{1,2}日|\d{1,2}月 ?\d{1,2}, ?\d{4}|[A-Z][a-z]{2,8} \d{1,2}, \d{4})\s*$")
TITLE_LINE = re.compile(r"\s-\s*(文字起こし|Transcript)\s*$")
VTT_VOICE = re.compile(r"<v\s+([^>]+)>")
TAG = re.compile(r"<[^>]+>")
SCREEN_SHARE = re.compile(r"presentation\s*\)?$|の(画面|発表)$|画面共有", re.I)
SEGMENT = re.compile(r"[^、。，,．.!！?？…\s]+[、。，,．.!！?？…\s]*")


def _non_speaker_labels() -> set[str]:
    return {x.lower() for lang in ("ja", "en") for x in load_locale(lang).get("non_speaker_labels", [])}


def valid_name(name: str) -> bool:
    n = name.strip()
    if not n or n[0] in "[(（【" or n[0].isdigit() or n.lower().startswith(("http", "www")):
        return False
    if re.search(r"[。、!?！？「」『』]", n) or n.endswith(".") or len(n.split()) > 4:
        return False
    return n.lower() not in _non_speaker_labels()


def ts_prefix(line: str):
    """Split a leading timestamp off a line: (seconds or None, rest)."""
    m = TS_PREFIX.match(line)
    if not m:
        return None, line
    return hms_to_sec(m.group(1) or m.group(2)), line[m.end():]


# ---------------------------------------------------------------- formats


def _meet_markers():
    return [load_locale("ja")["meet_markers"], load_locale("en")["meet_markers"]]


def is_meet(text: str) -> bool:
    head = text[:200000]
    return any(
        re.search(m["transcript_start"], head, re.M) or re.search(m["header"], head, re.M)
        for m in _meet_markers()
    )


def parse_meet(text: str) -> dict:
    markers = _meet_markers()
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if any(re.search(m["transcript_start"], line.strip()) for m in markers):
            start = i + 1
            break
    if start is None:
        for i, line in enumerate(lines):
            if any(re.search(m["header"], line.strip()) for m in markers):
                start = i
                break
    body = lines[start or 0:]
    utts, started_at, duration, block_t = [], None, None, None
    for line in body:
        s = line.replace("\u00a0", " ").strip()
        if not s or DATE_ONLY.match(s):
            continue
        header = next((re.search(m["header"], s) for m in markers if re.search(m["header"], s)), None)
        if header:
            gd = header.groupdict()
            if gd.get("y"):
                started_at = f"{gd['y']}-{int(gd['mo']):02d}-{int(gd['d']):02d}T{int(gd['h']):02d}:{gd['mi']}"
            continue
        if not utts and TITLE_LINE.search(s):
            continue  # "<title> - 文字起こし" header variant
        end = next((re.search(m["end"], s) for m in markers if re.search(m["end"], s)), None)
        if end:
            duration = hms_to_sec(end.group("ts"))
            break
        if any(re.search(m["footer"], s) for m in markers):
            break
        ts = TS_LINE.match(s)
        if ts:
            block_t = hms_to_sec(ts.group(1))
            continue
        sp = SPEAKER.match(s)
        if sp and valid_name(sp.group("name")):
            utts.append({"speaker": sp.group("name").strip(), "start": block_t, "text": sp.group("text").strip()})
        elif utts:
            utts[-1]["text"] += " " + s
        else:
            utts.append({"speaker": None, "start": block_t, "text": s})
    return {
        "source": "meet",
        "utterances": utts,
        "started_at": started_at,
        "duration_sec": duration,
        "duration_source": "end_marker" if duration is not None else None,
        "timestamp_granularity": "block" if any(u["start"] is not None for u in utts) else None,
    }


def parse_vtt(text: str) -> dict:
    lines = text.splitlines()
    cues, i = [], 0
    while i < len(lines):
        m = VTT_TIME.match(lines[i])
        if not m:
            i += 1
            continue
        start, end = hms_to_sec(m.group(1)), hms_to_sec(m.group(2))
        i += 1
        buf = []
        while i < len(lines) and lines[i].strip():
            if VTT_TIME.match(lines[i]):
                break
            if lines[i].strip().isdigit() and i + 1 < len(lines) and VTT_TIME.match(lines[i + 1]):
                i += 1  # cue number of the next cue, no blank line in between
                break
            buf.append(lines[i].strip())
            i += 1
        raw = " ".join(buf)
        voices = list(VTT_VOICE.finditer(raw))
        if voices:
            for k, v in enumerate(voices):
                stop = voices[k + 1].start() if k + 1 < len(voices) else len(raw)
                body = TAG.sub("", raw[v.end():stop]).strip()
                if body:
                    cues.append({"speaker": v.group(1).strip(), "start": start, "end": end, "text": body})
            continue
        speaker, body = None, TAG.sub("", raw).strip()
        sp = SPEAKER.match(body)
        if sp and valid_name(sp.group("name")):
            speaker, body = sp.group("name").strip(), sp.group("text").strip()
        if body:
            cues.append({"speaker": speaker, "start": start, "end": end, "text": body})
    merged = []
    for c in cues:
        prev = merged[-1] if merged else None
        if prev and prev["speaker"] == c["speaker"] and 0 <= c["start"] - prev["end"] <= 1.5:
            prev["text"] += " " + c["text"]
            prev["end"] = c["end"]
        else:
            merged.append(dict(c))
    last = max((c["end"] for c in merged), default=None)
    return {
        "source": "vtt",
        "utterances": merged,
        "started_at": None,
        "duration_sec": last,
        "duration_source": "last_cue_end" if last is not None else None,
        "timestamp_granularity": "utterance" if merged else None,
    }


def parse_plain(text: str) -> dict:
    lines = [l.replace("\u00a0", " ").rstrip() for l in text.splitlines()]
    nonempty = [l for l in lines if l.strip()]
    cand = Counter()
    for l in nonempty:
        o = OTTER_HEAD.match(l.strip())
        if o and valid_name(o.group("name")):
            cand[o.group("name").strip()] += 1
            continue
        sp = SPEAKER.match(ts_prefix(l.strip())[1])
        if sp and valid_name(sp.group("name")):
            cand[sp.group("name").strip()] += 1
    labels = {n for n, c in cand.items() if c >= 2}
    labeled = sum(cand[n] for n in labels)
    with_speakers = bool(labels) and labeled / max(len(nonempty), 1) >= 0.3
    if with_speakers:
        # once the document is clearly speaker-labelled, accept people who spoke only once
        labels |= {n for n, c in cand.items() if c == 1 and len(n) <= 20 and not re.search(r"\d", n)}

    utts = []
    for l in nonempty:
        s = l.strip()
        if with_speakers:
            o = OTTER_HEAD.match(s)
            if o and o.group("name").strip() in labels:
                utts.append({"speaker": o.group("name").strip(), "start": hms_to_sec(o.group("ts")), "text": ""})
                continue
        start, rest = ts_prefix(s)
        sp = SPEAKER.match(rest) if with_speakers else None
        if sp and sp.group("name").strip() in labels:
            utts.append({"speaker": sp.group("name").strip(), "start": start, "text": sp.group("text").strip()})
        elif with_speakers and utts and start is None:
            utts[-1]["text"] = (utts[-1]["text"] + " " + rest).strip()
        else:
            utts.append({"speaker": None, "start": start, "text": rest})
    utts = [u for u in utts if u["text"].strip()]
    starts = [u["start"] for u in utts if u["start"] is not None]
    return {
        "source": "plain" if with_speakers else "no-speaker",
        "utterances": utts,
        "started_at": None,
        "duration_sec": max(starts) if starts else None,
        "duration_source": "last_timestamp" if starts else None,
        "timestamp_granularity": "utterance" if starts else None,
    }


# ---------------------------------------------------------------- post-processing


def _strip_hallucinations(text: str, phrases: list[str]):
    hit = False
    out = unicodedata.normalize("NFKC", text)
    for p in phrases:
        pat = re.compile(re.escape(unicodedata.normalize("NFKC", p)) + r"[。.!！]?", re.I)
        if pat.search(out):
            hit = True
            out = pat.sub("", out)
    return out.strip(), hit


def split_lead_backchannel(text: str, is_bc) -> tuple[str, str, bool]:
    """Split leading backchannel words off an utterance.

    Returns (lead, rest, backchannel_only). Meet often glues the listener's
    "うん。うん。" onto the start of a turn, so it is counted apart from content.
    """
    segs = list(SEGMENT.finditer(text))
    k = 0
    while k < len(segs):
        core = "".join(tokens(segs[k].group(0)))
        if core and is_bc(core):
            k += 1
        else:
            break
    if k == 0:
        return "", text, False
    if k == len(segs):
        return "", text, True
    cut = segs[k].start()
    return text[:cut].strip(), text[cut:].strip(), False


def postprocess(parsed: dict, lang: str) -> dict:
    locale = load_locale(lang)
    halluc = load_locale("ja")["asr_hallucinations"] + load_locale("en")["asr_hallucinations"]
    is_bc = backchannel_token_matcher(locale)
    out, removed = [], []
    for u in parsed["utterances"]:
        original = u["text"].strip()
        if u.get("speaker") and SCREEN_SHARE.search(u["speaker"]):
            removed.append({"text": original, "speaker": u["speaker"], "reason": "screen_share"})
            continue
        text, hit = _strip_hallucinations(original, halluc)
        if hit:
            removed.append({"text": original, "speaker": u.get("speaker"), "reason": "asr_hallucination"})
        if not normalize(text):
            continue
        toks = tokens(text)
        lead, rest, bc_only = split_lead_backchannel(text, is_bc)
        looping = (
            not bc_only
            and len(toks) >= 8
            and Counter(toks).most_common(1)[0][1] / len(toks) > 0.6
        )
        out.append({
            "i": len(out),
            "speaker": u.get("speaker"),
            "start": u.get("start"),
            "end": u.get("end"),
            "text": rest,
            "lead_backchannel": lead,
            "backchannel_only": bc_only,
            "suspect_asr": hit or looping,
        })
    parsed["utterances"] = out
    parsed["removed"] = removed
    return parsed


def interpolate_block_times(parsed: dict, lang: str) -> None:
    """Meet only stamps every 1-2 minutes; spread each block's time over its turns by length."""
    utts = parsed["utterances"]
    if parsed.get("timestamp_granularity") != "block" or not utts:
        return
    blocks: list[list[dict]] = []
    for u in utts:
        if blocks and blocks[-1][0]["start"] == u["start"]:
            blocks[-1].append(u)
        else:
            blocks.append([u])
    rate = None
    for k, block in enumerate(blocks):
        t0 = block[0]["start"]
        if t0 is None:
            continue
        total = sum(max(units(x["lead_backchannel"] + x["text"], lang), 1) for x in block)
        if k + 1 < len(blocks) and blocks[k + 1][0]["start"] is not None:
            t1 = blocks[k + 1][0]["start"]
        elif parsed.get("duration_sec") is not None:
            t1 = parsed["duration_sec"]
        else:
            if rate is None:
                spoken = sum(max(units(x["lead_backchannel"] + x["text"], lang), 1) for b in blocks[:k] for x in b)
                rate = spoken / t0 if t0 > 0 and spoken else None
            t1 = t0 + total / rate if rate else None
            if t1 is not None:
                parsed["duration_sec"] = round(t1)
                parsed["duration_source"] = "estimated_from_last_block"
        if t1 is None or t1 <= t0:
            continue
        cum = 0
        for x in block:
            n = max(units(x["lead_backchannel"] + x["text"], lang), 1)
            x["start"] = round(t0 + (t1 - t0) * cum / total, 1)
            cum += n
            x["end"] = round(t0 + (t1 - t0) * cum / total, 1)
            x["time_estimated"] = True


def find_gaps(parsed: dict, lang: str, cfg: dict) -> list[dict]:
    """Long stretches with (almost) nothing transcribed: a break, silence, or a missing part.

    Exact when utterances have end times (VTT, audio); for Meet's periodic
    blocks a block with far less speech than usual counts; for logs with start
    times only, each turn's length is estimated from the transcript's own
    median pace (kind "estimated"), so a long monologue is not mistaken for a gap.
    """
    utts, gran, min_gap = parsed["utterances"], parsed.get("timestamp_granularity"), cfg["transcript_gap_sec"]
    out = []
    if gran == "utterance" and utts and all(u.get("end") is not None for u in utts):
        last_end = None
        for u in sorted(utts, key=lambda x: x["start"]):
            if last_end is not None and u["start"] - last_end >= min_gap:
                out.append({"from_sec": last_end, "to_sec": u["start"], "gap_sec": round(u["start"] - last_end), "kind": "silence"})
            last_end = u["end"] if last_end is None else max(last_end, u["end"])
    elif gran == "utterance" and len(utts) >= 4:
        # start times only: estimate how long each turn took from this transcript's own pace
        timed = [u for u in utts if u.get("start") is not None]
        pairs = [(max(units(a["lead_backchannel"] + a["text"], lang), 1), b["start"] - a["start"])
                 for a, b in zip(timed, timed[1:]) if b["start"] > a["start"]]
        if len(pairs) >= 3:
            rate = statistics.median(n / dt for n, dt in pairs)
            for a, b in zip(timed, timed[1:]):
                spoken = max(units(a["lead_backchannel"] + a["text"], lang), 1) / rate
                gap = b["start"] - (a["start"] + spoken)
                if gap >= min_gap:
                    out.append({"from_sec": round(a["start"] + spoken), "to_sec": b["start"], "gap_sec": round(gap), "kind": "estimated"})
    elif gran == "block":
        starts = sorted({u["start"] for u in utts if u["start"] is not None})
        bounds = starts + [parsed.get("duration_sec")]
        blocks = []
        for k, t0 in enumerate(starts):
            t1 = bounds[k + 1]
            if t1 is None or t1 <= t0:
                continue
            n = sum(max(units(u["lead_backchannel"] + u["text"], lang), 1) for u in utts if u["start"] == t0)
            blocks.append((t0, t1, n / (t1 - t0)))
        if len(blocks) >= 3:
            med = statistics.median(r for _, _, r in blocks)
            for t0, t1, r in blocks:
                if t1 - t0 >= min_gap and r < cfg["sparse_block_ratio"] * med:
                    out.append({"from_sec": t0, "to_sec": t1, "gap_sec": round(t1 - t0), "kind": "sparse"})
    return out


def read_text(path) -> str:
    """Decode a transcript file: UTF-8 (with or without BOM), UTF-16 with BOM, then Shift_JIS (cp932)."""
    data = Path(path).read_bytes() if not isinstance(path, bytes) else path
    if data[:4] == b"PK\x03\x04":
        raise SystemExit("this looks like a .docx/.zip file: export or save the transcript as plain text (.txt) and try again")
    if data[:5] == b"%PDF-":
        raise SystemExit("this is a PDF: copy the transcript text into a .txt file and try again")
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    for enc in ("utf-8-sig", "cp932"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise SystemExit("could not decode the transcript: save it as UTF-8 and try again")


def parse(text: str, lang: str | None = None) -> dict:
    text = text.replace("\ufeff", "")
    lang = lang or detect_language(text)
    if text.lstrip().startswith("WEBVTT") or re.search(VTT_TIME.pattern, text[:5000], re.M):
        parsed = parse_vtt(text)
    elif is_meet(text):
        parsed = parse_meet(text)
    else:
        parsed = parse_plain(text)
    return finalize(parsed, lang)


def finalize(parsed: dict, lang: str) -> dict:
    """Shared last steps for every input format (text transcripts and audio)."""
    removed_before = parsed.get("removed", [])
    parsed = postprocess(parsed, lang)
    parsed["removed"] = removed_before + parsed["removed"]
    gaps = find_gaps(parsed, lang, load_config())
    interpolate_block_times(parsed, lang)

    utts = parsed["utterances"]
    order: list[str] = []
    for u in utts:
        if u["speaker"] and u["speaker"] not in order:
            order.append(u["speaker"])
    locale = load_locale(lang)
    total_units = sum(units(u["text"], lang) for u in utts) or 1
    filler_density = sum(count_fillers(u["text"], locale) for u in utts) * 1000 / total_units
    if parsed["source"] == "meet":
        fillers_preserved = True
    elif parsed["source"] == "audio":
        fillers_preserved = None  # depends on the speech model; never assume
    else:
        fillers_preserved = True if filler_density >= 5 else None
    return {
        "version": 1,
        "source": parsed["source"],
        "language": lang,
        "has_speakers": len(order) >= 2,
        "has_timestamps": any(u["start"] is not None for u in utts),
        "timestamp_granularity": parsed.get("timestamp_granularity"),
        "fillers_preserved": fillers_preserved,
        "started_at": parsed.get("started_at"),
        "duration_sec": parsed.get("duration_sec"),
        "duration_source": parsed.get("duration_source"),
        "speakers": order,
        "utterances": utts,
        "removed": parsed["removed"],
        "gaps": gaps,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="transcript file, or - for stdin")
    ap.add_argument("-o", "--out")
    ap.add_argument("--lang", choices=["ja", "en"])
    a = ap.parse_args(argv)
    text = read_text(sys.stdin.buffer.read() if a.input == "-" else a.input)
    result = parse(text, a.lang)
    write_json(result, a.out)
    dur = result["duration_sec"]
    print(
        f"source={result['source']} lang={result['language']} speakers={result['speakers']} "
        f"utterances={len(result['utterances'])} duration_sec={dur} ({result['duration_source']}) "
        f"timestamps={result['timestamp_granularity']} fillers_preserved={result['fillers_preserved']} "
        f"removed={len(result['removed'])} gaps={len(result['gaps'])}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
