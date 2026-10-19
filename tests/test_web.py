"""The web app's Python bridge, run under CPython with the same scripts Pyodide loads."""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "meeting-coach"
sys.path.insert(0, str(ROOT / "tools"))

import build_web_manifest  # noqa: E402


class ManifestTest(unittest.TestCase):
    def test_manifest_is_current(self):
        on_disk = json.loads((ROOT / "web" / "manifest.json").read_text())
        self.assertEqual(on_disk, build_web_manifest.manifest(), "run tools/build_web_manifest.py")
        for f in on_disk["files"]:
            self.assertTrue((SKILL / f).is_file(), f)

    def test_prompt_sections_exist(self):
        skill = (SKILL / "SKILL.md").read_text()
        for marker in ("### 4. Judge", "### 5.", "## Prepare (before the meeting)", "## Review (after the meeting)"):
            self.assertIn(marker, skill)  # web/prompts.js cuts SKILL.md at these headings


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self._env = {k: os.environ.get(k) for k in ("HOME", "MC_SKILL_SCRIPTS")}
        os.environ["HOME"] = self.home.name
        os.environ["MC_SKILL_SCRIPTS"] = str(SKILL / "scripts")
        sys.path.insert(0, str(ROOT / "web"))
        self.b = importlib.import_module("bridge")

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.home.cleanup()

    def test_full_review_round_trip(self):
        b = self.b
        t = b.parse(str(ROOT / "examples" / "ja-1on1-plain.txt"))
        meta = (ROOT / "examples" / "ja-1on1-plain.meta.json").read_text()
        m = b.measure(t, meta)
        rub = json.loads((SKILL / "config.default.json").read_text())["rubrics"]["one-on-one/report"]
        j = json.dumps({"criteria": [{"id": k, "level": 3, "evidence": [{"i": 7, "quote": "今期の期待値を確認させてください"}]}
                                     for k in list(rub["meeting"]) + list(rub["self"])],
                        "next_actions": [{"text": "冒頭で目的を言う"}], "habits": [{"id": "conclusion_late", "label": "結論が後ろ"}]})
        self.assertTrue(json.loads(b.verify(j, t))["ok"])
        s = json.loads(b.score(j, meta, m))
        self.assertEqual(s["result"]["meeting"]["score"], 75)
        self.assertIn("会議点: 75", s["markdown"])
        saved = json.loads(b.save(j, json.dumps(s["result"]), t, meta))
        self.assertTrue(saved["new_action_ids"])
        self.assertEqual(len(json.loads(b.history())), 1)
        self.assertIn("冒頭で目的を言う", b.learnings_md())
        self.assertEqual(json.loads(b.summary())["open_actions"][0]["text"], "冒頭で目的を言う")

    def test_parse_reports_unsupported_files(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.docx"
            p.write_bytes(b"PK\x03\x04junk")
            self.assertIn(".txt", json.loads(self.b.parse(str(p)))["error"])

    def test_prep_block_backup_restore_wipe(self):
        b = self.b
        rec = json.loads(b.prep_save(json.dumps({"date": "2026-10-09", "meeting_type": "one-on-one", "my_position": "report",
                                                 "goal": "判断材料を得る", "intents": ["仕事内容を聞く"], "language": "ja"})))
        self.assertEqual(json.loads(b.prep_find("2026-10-09"))["id"], rec["id"])
        block = b.export_block("ja")
        backup = b.backup()
        self.assertGreater(json.loads(b.wipe())["deleted"], 0)
        self.assertIsNone(json.loads(b.prep_find("2026-10-09")))
        self.assertEqual(json.loads(b.import_block(block, "ja"))["plans"], 1)
        self.assertEqual(json.loads(b.prep_find("2026-10-09"))["id"], rec["id"])
        b.wipe()
        self.assertGreater(json.loads(b.restore(backup))["restored"], 0)
        self.assertEqual(json.loads(b.prep_find("2026-10-09"))["id"], rec["id"])

    def test_restore_only_writes_data_files_inside_the_store(self):
        evil = json.dumps({"format": "meeting-coach-backup", "files": {
            "../escaped.txt": "x", "config.json": '{"redact_names": false}', "ok.txt": "y",
            "learnings.md": "z", "prep/P-20261009-1.json": "{}", "reviews/../../x.md": "w"}})
        self.assertEqual(json.loads(self.b.backup_info(evil))["files"], 2)
        self.assertEqual(json.loads(self.b.restore(evil))["restored"], 2)
        self.assertFalse((Path(self.home.name) / "escaped.txt").exists())
        self.assertFalse((Path(self.home.name) / ".meeting-coach" / "config.json").exists())
        self.assertIn("error", json.loads(self.b.restore('{"format": "other"}')))
        self.assertIn("error", json.loads(self.b.restore("not json")))  # a traceback never reaches the page

    def test_import_requires_the_block_tag(self):
        self.assertIn("error", json.loads(self.b.import_block("会議の文字起こしを間違えて貼った", "ja")))


if __name__ == "__main__":
    unittest.main()
