#!/usr/bin/env python3
"""Turn a meeting recording (audio or video) into the common transcript JSON, locally.

Pipeline: ffmpeg extracts 16 kHz mono audio, a Whisper command-line tool on this
machine writes JSON with segment times, and the segments become utterances with
real start and end times. Nothing is uploaded.

Speakers are not separated here. Assign them from context afterwards with
assign_speakers.py, as for any transcript without speaker labels.

Engines (the first one found is used unless --engine is given):
  mlx      mlx_whisper   Apple Silicon   (uv tool install mlx-whisper)
  whisper  whisper       any machine     (pip install openai-whisper)

A Whisper JSON made elsewhere can be converted directly with --from-json.

Usage:
  python3 transcribe.py RECORDING [-o transcript.json] [--lang ja|en] [--engine auto|mlx|whisper] [--model NAME]
  python3 transcribe.py --from-json whisper.json [-o transcript.json] [--lang ja|en] [--duration SECONDS]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True  # keep the skill folder clean

from parse_transcript import finalize
from common import write_json

ENGINES = {
    "mlx": ("mlx_whisper", "mlx-community/whisper-large-v3-turbo"),
    "whisper": ("whisper", "turbo"),
}
# A short prompt in the spoken style nudges Whisper to keep fillers and backchannels
# instead of tidying them away. A heuristic, not a guarantee: check fillers_preserved.
STYLE_PROMPT = {
    "ja": "えー、あの、うーん。はい、はい。そうですね。なるほど。",
    "en": "Um, uh, yeah. Right. Mm-hmm. So, you know.",
}
# Whisper's own signals for a segment that is probably silence or invented text.
NO_SPEECH_PROB = 0.6
LOW_LOGPROB = -1.0


def find_engine(preferred: str = "auto"):
    names = list(ENGINES) if preferred == "auto" else [preferred]
    for name in names:
        exe = shutil.which(ENGINES[name][0])
        if exe:
            return name, exe
    raise SystemExit(
        "no local Whisper found: on Apple Silicon run `uv tool install mlx-whisper`, "
        "elsewhere `pip install openai-whisper`; or pass an existing Whisper JSON with --from-json"
    )


def need(tool: str) -> str:
    exe = shutil.which(tool)
    if not exe:
        raise SystemExit(f"{tool} not found: install ffmpeg (it provides {tool})")
    return exe


def extract_audio(src: Path, dst: Path) -> None:
    subprocess.run([need("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
                    "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(dst)], check=True)


def audio_seconds(path: Path):
    out = subprocess.run([need("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return round(float(out.stdout.strip()), 1)
    except ValueError:
        return None


def run_engine(engine: str, exe: str, wav: Path, outdir: Path, lang: str | None, model: str | None) -> Path:
    model = model or ENGINES[engine][1]
    prompt = STYLE_PROMPT.get(lang or "", "")
    if engine == "mlx":
        cmd = [exe, str(wav), "--model", model, "--output-format", "json", "--output-dir", str(outdir),
               "--word-timestamps", "True", "--hallucination-silence-threshold", "2",
               "--condition-on-previous-text", "False", "--verbose", "False"]
        if lang:
            cmd += ["--language", lang]
        if prompt:
            cmd += ["--initial-prompt", prompt]
    else:
        cmd = [exe, str(wav), "--model", model, "--output_format", "json", "--output_dir", str(outdir),
               "--word_timestamps", "True", "--hallucination_silence_threshold", "2",
               "--condition_on_previous_text", "False", "--verbose", "False"]
        if lang:
            cmd += ["--language", lang]
        if prompt:
            cmd += ["--initial_prompt", prompt]
    subprocess.run(cmd, check=True)
    found = sorted(outdir.glob("*.json"))
    if not found:
        raise SystemExit(f"{engine} finished but wrote no JSON (is ffmpeg on PATH for it?)")
    return found[0]


def from_whisper_json(data: dict, lang: str | None = None, duration: float | None = None) -> dict:
    """Whisper's JSON (segments with start/end/text) -> the common transcript JSON."""
    lang = lang or (data.get("language") if data.get("language") in ("ja", "en") else None) or "en"
    utts, removed = [], []
    for seg in data.get("segments", []):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if (seg.get("no_speech_prob") or 0) > NO_SPEECH_PROB and (seg.get("avg_logprob") or 0) < LOW_LOGPROB:
            removed.append({"text": text, "speaker": None, "reason": "no_speech"})
            continue
        utts.append({"speaker": None, "start": round(float(seg["start"]), 2), "end": round(float(seg["end"]), 2), "text": text})
    last_end = max((u["end"] for u in utts), default=None)
    parsed = {
        "source": "audio",
        "utterances": utts,
        "removed": removed,
        "started_at": None,
        "duration_sec": duration if duration is not None else last_end,
        "duration_source": "audio_length" if duration is not None else ("last_segment_end" if last_end is not None else None),
        "timestamp_granularity": "utterance" if utts else None,
    }
    return finalize(parsed, lang)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recording", nargs="?", help="audio or video file")
    ap.add_argument("--from-json", help="convert an existing Whisper JSON instead of transcribing")
    ap.add_argument("-o", "--out")
    ap.add_argument("--lang", choices=["ja", "en"])
    ap.add_argument("--engine", choices=["auto", *ENGINES], default="auto")
    ap.add_argument("--model")
    ap.add_argument("--duration", type=float, help="recording length in seconds (with --from-json)")
    a = ap.parse_args(argv)

    if a.from_json:
        result = from_whisper_json(json.loads(Path(a.from_json).read_text(encoding="utf-8")), a.lang, a.duration)
    else:
        if not a.recording:
            ap.error("give a recording, or --from-json")
        src = Path(a.recording)
        if not src.is_file():
            raise SystemExit(f"not found: {src}")
        engine, exe = find_engine(a.engine)
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "audio.wav"
            extract_audio(src, wav)
            seconds = audio_seconds(wav)
            print(f"transcribing {seconds}s of audio with {engine} (local)…", file=sys.stderr)
            data = json.loads(run_engine(engine, exe, wav, Path(d), a.lang, a.model).read_text(encoding="utf-8"))
        result = from_whisper_json(data, a.lang, seconds)

    write_json(result, a.out)
    print(f"source=audio lang={result['language']} utterances={len(result['utterances'])} "
          f"duration_sec={result['duration_sec']} removed={len(result['removed'])} gaps={len(result['gaps'])} "
          f"(no speaker labels: assign them with assign_speakers.py)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
