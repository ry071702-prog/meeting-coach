#!/usr/bin/env python3
"""Fetch a public web page (a profile, a company page) as plain text with headings.

Used by prepare mode so facts are read from the page itself, not from a
summary. Only fetches the URL it is given.

Usage:
  python3 fetch_profile.py URL|FILE [--stop-at HEADING ...] [--max-chars N]

--stop-at drops everything from the first heading whose text matches (for
example a "More people" block that lists other employees).
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True  # keep the skill folder clean

UA = "Mozilla/5.0 (meeting-coach prepare mode)"
DROP = re.compile(r"(?is)<(script|style|noscript|svg|template|iframe|nav|footer|header|form)\b[^>]*>.*?</\1>")
BLOCK = re.compile(r"(?i)<(br|/p|/div|/li|/dt|/dd|/tr|/section|/article|/blockquote)\b[^>]*>")


def fetch(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        raise SystemExit("only http(s) URLs can be fetched")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        charset = r.headers.get_content_charset()
    if not charset:
        m = re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', raw[:4000], re.I)
        charset = m.group(1).decode() if m else "utf-8"
    return raw.decode(charset, errors="replace")


def to_text(page: str, stop_at: list[str] | None = None) -> str:
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
    body = DROP.sub("", page)
    main = re.search(r"(?is)<main\b.*?</main>", body) or re.search(r"(?is)<article\b.*?</article>", body) \
        or re.search(r"(?is)<body\b.*?</body>", body)
    b = main.group(0) if main else body
    b = re.sub(r"(?i)<h([1-6])\b[^>]*>", lambda m: "\n" + "#" * int(m.group(1)) + " ", b)
    b = re.sub(r"(?i)</h[1-6]>", "\n", b)
    b = BLOCK.sub("\n", b)
    text = html.unescape(re.sub(r"<[^>]+>", "", b))
    lines = [re.sub(r"[ \t　]+", " ", l).strip() for l in text.splitlines()]
    out = []
    for l in lines:
        if not l:
            continue
        if stop_at and l.startswith("#") and l.lstrip("# ").strip() in stop_at:
            break
        out.append(l)
    head = f"TITLE: {html.unescape(title.group(1)).strip()}\n" if title else ""
    return head + "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="URL or a saved .html file")
    ap.add_argument("--stop-at", nargs="*", default=[], help="heading texts where the useful part ends")
    ap.add_argument("--max-chars", type=int, default=20000)
    a = ap.parse_args(argv)
    if a.source.startswith(("http://", "https://")):
        try:
            page, src = fetch(a.source), a.source
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print(f"FETCH FAILED: {a.source}: {e}  (treat anything learned only from a search summary of this page as unverified)")
            return 1
    else:
        page, src = Path(a.source).read_text(encoding="utf-8", errors="replace"), a.source
    text = to_text(page, a.stop_at)
    print(f"SOURCE: {src}")
    print(text[: a.max_chars])
    if len(text) > a.max_chars:
        print(f"\n[truncated at {a.max_chars} characters]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
