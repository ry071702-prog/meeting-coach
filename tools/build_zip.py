#!/usr/bin/env python3
"""Build dist/meeting-coach.zip for Claude.ai (the skill folder at the zip root)."""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "meeting-coach"
OUT = ROOT / "dist" / "meeting-coach.zip"

OUT.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted(SKILL.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc" and p.name != ".DS_Store":
            z.write(p, Path("meeting-coach") / p.relative_to(SKILL))
    z.write(ROOT / "LICENSE", Path("meeting-coach") / "LICENSE")
print(OUT, sum(1 for _ in zipfile.ZipFile(OUT).namelist()), "files", file=sys.stderr)
