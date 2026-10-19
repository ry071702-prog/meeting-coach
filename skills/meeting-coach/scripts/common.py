"""Shared helpers for the meeting-coach scripts (stdlib only)."""
from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
LOCALE_DIR = Path(__file__).resolve().parent / "locales"
DEFAULT_CONFIG = SKILL_DIR / "config.default.json"

_JA_CHAR = re.compile(r"[぀-ヿ㐀-鿿]")
_PUNCT = re.compile(r"[\s、。，,．.!！?？「」『』（）()\[\]【】…・\-—–\"'“”‘’:：;；〜~]+")
_TOKEN_SPLIT = re.compile(r"[\s、。，,．.!！?？…]+")


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(data, path=None):
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if path:
        Path(path).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path=None, store=None) -> dict:
    """Default config, overlaid by <store>/config.json (store defaults to store_dir), overlaid by an explicit path."""
    cfg = read_json(DEFAULT_CONFIG)
    user = Path(os.path.expanduser(store or cfg["store_dir"])) / "config.json"
    if user.is_file():
        cfg = _deep_merge(cfg, read_json(user))
    if path:
        cfg = _deep_merge(cfg, read_json(path))
    return cfg


def store_dir(cfg: dict, override=None) -> Path:
    return Path(os.path.expanduser(override or cfg["store_dir"]))


def load_locale(lang: str) -> dict:
    p = LOCALE_DIR / f"{lang}.json"
    if not p.is_file():
        p = LOCALE_DIR / "en.json"
    return read_json(p)


def detect_language(text: str) -> str:
    sample = text[:20000]
    letters = sum(1 for c in sample if c.isalpha())
    if not letters:
        return "en"
    return "ja" if len(_JA_CHAR.findall(sample)) / letters > 0.2 else "en"


def normalize(text: str) -> str:
    """Comparison form: NFKC, lower-case, no whitespace or punctuation."""
    return _PUNCT.sub("", unicodedata.normalize("NFKC", text)).lower()


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_SPLIT.split(unicodedata.normalize("NFKC", text).lower()) if t]


def units(text: str, lang: str) -> int:
    """Length used for talk share: characters for Japanese, words otherwise."""
    if lang == "ja":
        return len(normalize(text))
    return len(re.findall(r"[A-Za-z0-9']+", text))


def split_sentences(text: str, lang: str) -> list[str]:
    pat = r"(?<=[。！？!?])" if lang == "ja" else r"(?<=[.!?])\s+"
    return [s.strip() for s in re.split(pat, text) if s.strip()]


def is_question(sentence: str, locale: dict) -> bool:
    s = sentence.strip()
    if s.endswith(("?", "？")):
        return True
    if locale["language"] == "ja":
        core = re.sub(r"[。．.!！\s]+$", "", s)
        return any(re.search(f"(?:{e})$", core) for e in locale["question_endings"])
    words = re.findall(r"[a-z']+", s.lower())
    return len(words) >= 3 and words[0] in locale.get("question_starts", [])


def _bc_vocab(locale: dict) -> list[str]:
    return sorted({unicodedata.normalize("NFKC", b).lower() for b in locale["backchannels"]}, key=len, reverse=True)


def backchannel_token_matcher(locale: dict):
    """Return f(token) -> True when a single token is a backchannel.

    Japanese tokens may repeat without punctuation ("うんうんうん"), so a token
    matches when it is any concatenation of backchannel words.
    """
    vocab = _bc_vocab(locale)
    if locale["language"] == "ja":
        pat = re.compile("(?:" + "|".join(map(re.escape, vocab)) + ")+")
        return lambda t: bool(pat.fullmatch(t))
    single = {v for v in vocab if " " not in v}
    return lambda t: t in single


def is_backchannel_only(text: str, locale: dict) -> bool:
    toks = tokens(text)
    if not toks:
        return False
    match = backchannel_token_matcher(locale)
    if all(match(t) for t in toks):
        return True
    if locale["language"] == "ja":
        return False
    # English backchannels can span several words ("that makes sense").
    s = " " + " ".join(toks) + " "
    changed = True
    while changed:
        changed = False
        for b in _bc_vocab(locale):
            if f" {b} " in s:
                s = s.replace(f" {b} ", " ")
                changed = True
    return not s.strip()


def count_fillers(text: str, locale: dict) -> int:
    fillers = [unicodedata.normalize("NFKC", f).lower() for f in locale["fillers"]]
    single = {f for f in fillers if " " not in f}
    multi = [f for f in fillers if " " in f]
    n = sum(1 for t in tokens(text) if t in single)
    low = text.lower()
    n += sum(len(re.findall(r"\b" + re.escape(m) + r"\b", low)) for m in multi)
    return n


def find_phrases(text: str, phrases: list[str]) -> list[str]:
    norm = unicodedata.normalize("NFKC", text).lower()
    return [p for p in phrases if unicodedata.normalize("NFKC", p).lower() in norm]


def matches_any(text: str, patterns: list[str]) -> bool:
    low = unicodedata.normalize("NFKC", text).lower()
    return any(re.search(p, low) for p in patterns)


def hms_to_sec(ts: str) -> float:
    parts = [float(p) for p in ts.replace(",", ".").split(":")]
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec
