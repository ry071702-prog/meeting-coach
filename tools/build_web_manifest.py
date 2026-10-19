#!/usr/bin/env python3
"""Write web/manifest.json: the skill files the web app loads into Pyodide and its prompts."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "meeting-coach"


def manifest() -> dict:
    files = sorted(
        str(p.relative_to(SKILL)) for p in SKILL.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix in (".py", ".json", ".md")
    )
    return {"skill_base": "../skills/meeting-coach/", "files": files}


if __name__ == "__main__":
    out = ROOT / "web" / "manifest.json"
    out.write_text(json.dumps(manifest(), indent=2) + "\n", encoding="utf-8")
    print(out, len(manifest()["files"]), "files")
