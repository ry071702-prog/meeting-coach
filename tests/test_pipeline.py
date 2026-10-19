"""Unit tests for meeting-coach scripts. Run: python3 -m unittest discover tests"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "meeting-coach"
sys.path.insert(0, str(SKILL / "scripts"))

import assign_speakers  # noqa: E402
import fetch_profile  # noqa: E402
import learnings  # noqa: E402
import metrics  # noqa: E402
import parse_transcript  # noqa: E402
import score  # noqa: E402
import transcribe  # noqa: E402
import verify_evidence  # noqa: E402
from common import is_backchannel_only, load_config, load_locale  # noqa: E402

EX = ROOT / "examples"
CFG = json.loads((SKILL / "config.default.json").read_text(encoding="utf-8"))


def parse_file(name: str) -> dict:
    return parse_transcript.parse((EX / name).read_text(encoding="utf-8"))


def meta(name: str) -> dict:
    return json.loads((EX / name).read_text(encoding="utf-8"))


class ParseTest(unittest.TestCase):
    def test_meet_ja(self):
        t = parse_file("ja-external-meet.txt")
        self.assertEqual(t["source"], "meet")
        self.assertEqual(t["language"], "ja")
        self.assertEqual(t["speakers"], ["佐藤", "田中"])
        self.assertEqual(t["duration_sec"], 55 * 60 + 10)
        self.assertEqual(t["duration_source"], "end_marker")
        self.assertEqual(t["started_at"], "2026-10-01T14:00")
        self.assertTrue(t["fillers_preserved"])
        # footer and summary are not utterances
        self.assertFalse(any("コンピュータが生成" in u["text"] for u in t["utterances"]))
        self.assertFalse(any("概要" == u["text"] for u in t["utterances"]))
        # block timestamps are spread over the turns and stay monotonic
        starts = [u["start"] for u in t["utterances"]]
        self.assertEqual(starts, sorted(starts))
        self.assertTrue(all(u.get("time_estimated") for u in t["utterances"]))

    def test_lead_backchannel_split(self):
        t = parse_transcript.parse("📖 文字起こし\n00:00:00\nA: ああ。うん。うん。えっと、それで本題です。\nB: うん。うん。\nA: はい\n")
        a0, b, a1 = t["utterances"]
        self.assertEqual(a0["lead_backchannel"], "ああ。うん。うん。")
        self.assertTrue(a0["text"].startswith("えっと"))
        self.assertTrue(b["backchannel_only"])
        self.assertTrue(a1["backchannel_only"])

    def test_plain_with_timestamps(self):
        t = parse_file("ja-1on1-plain.txt")
        self.assertEqual(t["source"], "plain")
        self.assertEqual(t["speakers"], ["山本", "佐藤"])
        self.assertEqual(t["utterances"][0]["start"], 5)
        self.assertEqual(t["duration_source"], "last_timestamp")

    def test_vtt_teams_voice_tags(self):
        t = parse_file("en-team-meeting.vtt")
        self.assertEqual(t["source"], "vtt")
        self.assertEqual(t["language"], "en")
        self.assertEqual(t["speakers"], ["Alex", "Jordan", "Sam"])
        self.assertEqual(t["duration_sec"], 38 * 60)
        self.assertTrue(t["utterances"][3]["backchannel_only"])  # "Yeah."

    def test_vtt_zoom_name_prefix_and_merge(self):
        vtt = ("WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.000\nKim: Hello there.\n\n"
               "2\n00:00:03.500 --> 00:00:05.000\nKim: Second part.\n\n"
               "3\n00:00:06.000 --> 00:00:08.000\nLee: Hi Kim.\n")
        t = parse_transcript.parse(vtt)
        self.assertEqual([u["speaker"] for u in t["utterances"]], ["Kim", "Lee"])
        self.assertEqual(t["utterances"][0]["text"], "Hello there. Second part.")

    def test_urls_and_one_off_colons_are_not_speakers(self):
        text = "See https://example.com/a for details\nNote: this line has a colon\nanother line\nand one more\n"
        t = parse_transcript.parse(text, "en")
        self.assertEqual(t["source"], "no-speaker")
        self.assertFalse(t["has_speakers"])

    def test_no_speaker_and_asr_hallucination_removed(self):
        text = "今日は予算の話をします\nご視聴ありがとうございました\n来週までに決めましょう\n"
        t = parse_transcript.parse(text)
        self.assertEqual(t["source"], "no-speaker")
        self.assertEqual(len(t["utterances"]), 2)
        self.assertEqual(t["removed"][0]["reason"], "asr_hallucination")

    def test_otter_style(self):
        text = "Ana  0:05\nHi all, quick sync.\nBen  0:12\nSure.\nAna  0:20\nLet's start.\n"
        t = parse_transcript.parse(text, "en")
        self.assertEqual(t["speakers"], ["Ana", "Ben"])
        self.assertEqual(t["utterances"][1]["start"], 12)


class BackchannelTest(unittest.TestCase):
    def test_ja(self):
        loc = load_locale("ja")
        for s in ("はい", "うんうんうん", "なるほどですね。", "はい、はい、そうですね"):
            self.assertTrue(is_backchannel_only(s, loc), s)
        for s in ("はい、わかりました。来週出します", "うーん、そうですね"):
            self.assertFalse(is_backchannel_only(s, loc), s)

    def test_en_multiword(self):
        loc = load_locale("en")
        self.assertTrue(is_backchannel_only("Yeah, that makes sense.", loc))
        self.assertFalse(is_backchannel_only("Yeah, but the cost is high.", loc))


class MetricsTest(unittest.TestCase):
    def test_external_example(self):
        m = metrics.compute(parse_file("ja-external-meet.txt"), meta("ja-external-meet.meta.json"), CFG)
        self.assertAlmostEqual(m["duration"]["overrun_ratio"], (3310 - 1800) / 1800, places=3)
        self.assertGreater(m["my_share"], 0.8)
        self.assertEqual(m["counterpart_questions"], 0)
        self.assertTrue(m["my_long_turns"])
        self.assertTrue(m["thin_responses"])
        unresolved = [h for h in m["hedge_candidates"] if h["phrase"] == "検討します"]
        self.assertTrue(unresolved and not unresolved[0]["followed_by_commitment"])
        self.assertTrue(m["closing"]["closing_phrase_only"])
        self.assertIn("silences_after_my_questions", m["unavailable"])

    def test_resolved_hedge_is_followed_by_deadline(self):
        m = metrics.compute(parse_file("ja-1on1-plain.txt"), meta("ja-1on1-plain.meta.json"), CFG)
        self.assertTrue(all(h["followed_by_commitment"] for h in m["hedge_candidates"]))
        self.assertFalse(m["closing"]["closing_phrase_only"])

    def test_en_stacked_and_silence(self):
        m = metrics.compute(parse_file("en-team-meeting.vtt"), meta("en-team-meeting.meta.json"), CFG)
        self.assertEqual(m["my_stacked_questions"][0]["questions"], 3)
        self.assertFalse(m["my_question_then_kept_talking"])  # only questions followed
        self.assertTrue(m["silences_after_my_questions"])
        check = [h for h in m["hedge_candidates"] if h["phrase"] == "let me check with"]
        self.assertFalse(check[0]["followed_by_commitment"])

    def test_without_speakers_marks_unavailable(self):
        t = parse_transcript.parse("今日は予算の話をします\n来週までに決めましょう\n")
        m = metrics.compute(t, {"me": "佐藤"}, CFG)
        self.assertIn("talk_share", m["unavailable"])
        self.assertNotIn("my_share", m)

    def test_unknown_me(self):
        m = metrics.compute(parse_file("ja-1on1-plain.txt"), {"me": "鈴木"}, CFG)
        self.assertIn("my_metrics", m["unavailable"])


def judgement(levels: dict) -> dict:
    return {"criteria": [{"id": k, "level": v, "evidence": []} for k, v in levels.items()]}


class ScoreTest(unittest.TestCase):
    def setUp(self):
        self.rub = CFG["rubrics"]["external"]

    def all_levels(self, lv):
        return {**{k: lv for k in self.rub["meeting"]}, **{k: lv for k in self.rub["self"]}}

    def test_perfect_no_overrun(self):
        r = score.compute(judgement(self.all_levels(4)), {"meeting_type": "external"}, None, CFG)
        self.assertEqual((r["meeting"]["score"], r["self"]["score"]), (100, 100))
        self.assertEqual(r["meeting"]["band"], "S")

    def test_null_is_dropped_not_zero(self):
        lv = self.all_levels(4)
        lv["participation_balance"] = None
        r = score.compute(judgement(lv), {"meeting_type": "external"}, None, CFG)
        self.assertEqual(r["meeting"]["score"], 100)
        self.assertEqual(r["meeting"]["coverage"], 0.85)

    def test_low_coverage_flag(self):
        lv: dict = {k: None for k in self.all_levels(0)}
        lv["purpose_shared"] = 3
        r = score.compute(judgement(lv), {"meeting_type": "external"}, None, CFG)
        self.assertTrue(r["meeting"]["low_confidence"])
        self.assertIsNone(r["self"]["score"])

    def test_time_penalty_tiers(self):
        cases = [(32, 0), (36, 5), (44, 10), (55, 20)]
        for actual, pts in cases:
            m = {"meeting_type": "external", "scheduled_minutes": 30, "actual_minutes": actual}
            r = score.compute(judgement(self.all_levels(4)), m, None, CFG)
            self.assertEqual(r["meeting"]["score"], 100 - pts, actual)

    def test_self_penalised_only_when_facilitating(self):
        base = {"meeting_type": "external", "scheduled_minutes": 30, "actual_minutes": 55, "me": "佐藤"}
        other = score.compute(judgement(self.all_levels(4)), {**base, "facilitator": "田中"}, None, CFG)
        mine = score.compute(judgement(self.all_levels(4)), {**base, "facilitator": "me"}, None, CFG)
        named = score.compute(judgement(self.all_levels(4)), {**base, "facilitator": "佐藤"}, None, CFG)
        self.assertEqual(other["self"]["score"], 100)
        self.assertEqual(mine["self"]["score"], 80)
        self.assertEqual(named["self"]["score"], 80)
        self.assertEqual(other["meeting"]["score"], 80)

    def test_weights_and_rounding(self):
        lv = self.all_levels(4)
        lv["discovery"] = 2  # weight 25 -> loses 12.5
        r = score.compute(judgement(lv), {"meeting_type": "external"}, None, CFG)
        self.assertEqual(r["self"]["score"], 88)

    def test_errors(self):
        r = score.compute(judgement({"purpose_shared": 5, "made_up": 2}), {"meeting_type": "external"}, None, CFG)
        self.assertEqual(len(r["errors"]), 2)
        r = score.compute(judgement({}), {"meeting_type": "one-on-one", "my_position": "boss"}, None, CFG)
        self.assertTrue(r["errors"])

    def test_one_on_one_rubric_key(self):
        self.assertEqual(score.rubric_key({"meeting_type": "one-on-one", "my_position": "manager"}), "one-on-one/manager")
        self.assertEqual(score.rubric_key({"meeting_type": "one-on-one"}), "one-on-one/peer")

    def test_markdown_labels(self):
        r = score.compute(judgement(self.all_levels(3)), {"meeting_type": "external"}, None, CFG)
        md = score.to_markdown(r, "ja")
        self.assertIn("会議点: 75 (A 良い)", md)
        self.assertIn("課題の聞き出し", md)
        lv = self.all_levels(4)
        lv["decisions_clear"] = 1  # 25 * 1/4 = 6.25 must not display as 6.2
        md = score.to_markdown(score.compute(judgement(lv), {"meeting_type": "external"}, None, CFG), "ja")
        self.assertIn("| 6.25 |", md)


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.t = parse_file("ja-1on1-plain.txt")

    def run_v(self, evidence, level: int | None = 2):
        j = {"criteria": [{"id": "x", "level": level, "evidence": evidence}]}
        return verify_evidence.verify(j, self.t)

    def test_exact_and_punctuation_insensitive(self):
        self.assertTrue(self.run_v([{"i": 5, "quote": "いつ頃までにお返事をいただけそうでしょうか"}])["ok"])
        self.assertTrue(self.run_v([{"i": 5, "quote": "いつ頃までに、お返事を いただけそうでしょうか？"}])["ok"])

    def test_ellipsis_pieces_in_order(self):
        self.assertTrue(self.run_v([{"i": 7, "quote": "評価面談の前に…成功はどういう状態ですか"}])["ok"])
        self.assertFalse(self.run_v([{"i": 7, "quote": "成功はどういう状態ですか…評価面談の前に"}])["ok"])

    def test_wrong_index_fails_with_hint(self):
        for i in (6, 0):  # a neighbour is not good enough: it may be someone else's line
            res = self.run_v([{"i": i, "quote": "いつ頃までにお返事"}])
            self.assertFalse(res["ok"])
            self.assertIn("it is in i=[5]", res["failures"][0])

    def test_paraphrase_rejected(self):
        res = self.run_v([{"i": 5, "quote": "いつ返事をもらえますか"}])
        self.assertFalse(res["ok"])

    def test_scored_needs_evidence_and_absence_range(self):
        self.assertFalse(self.run_v([])["ok"])
        self.assertTrue(self.run_v([], level=None)["ok"])
        self.assertTrue(self.run_v([{"absence": "no recap", "range": [10, 13]}])["ok"])
        self.assertFalse(self.run_v([{"absence": "no recap", "range": [10, 99]}])["ok"])
        self.assertFalse(self.run_v([{"absence": "", "range": [10, 13]}])["ok"])

    def test_speaker_mismatch(self):
        res = self.run_v([{"i": 5, "quote": "いつ頃までにお返事", "speaker": "山本"}])
        self.assertFalse(res["ok"])


class LearningsTest(unittest.TestCase):
    def _run(self, root, date, next_actions, checks=()):
        t = parse_file("ja-external-meet.txt")
        m = {**meta("ja-external-meet.meta.json"), "date": date}
        rub = CFG["rubrics"]["external"]
        j = {
            "criteria": [{"id": k, "level": 2, "reason": "田中さんの反応が薄い", "evidence": [
                {"i": 6, "quote": "いかがでしょうか"}, {"i": 7, "quote": "うーん"}]}
                for k in list(rub["meeting"]) + list(rub["self"])],
            "signals": [{"type": "hedge_unresolved", "i": 14, "quote": "前向きに検討します", "verdict": "risk"}],
            "next_actions": [{"text": t_} for t_ in next_actions],
            "habits": [{"id": "conclusion_late", "label": "結論が後ろ"}],
            "worked": ["冒頭で名乗った"],
            "previous_actions_check": list(checks),
        }
        s_ = score.compute(j, m, None, CFG)
        return learnings.save(j, s_, t, m, CFG, root)

    def test_two_reviews_close_the_loop(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            r1 = self._run(root, "2026-10-01", ["『検討します』には期日を聞く"])
            aid = r1["new_action_ids"][0]
            self.assertEqual(aid, "A-20261001-1")
            r2 = self._run(root, "2026-10-08", ["冒頭で目的を言う"], [{"id": aid, "done": True}])
            state = json.loads((root / "learnings.json").read_text())
            first = next(a for a in state["actions"] if a["id"] == aid)
            self.assertEqual(first["status"], "done")
            self.assertEqual(state["habits"]["conclusion_late"]["count"], 2)
            self.assertEqual(len((root / "history.jsonl").read_text().splitlines()), 2)
            self.assertTrue(Path(r2["review"]).is_file())

    def test_counterpart_words_and_names_not_stored(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._run(root, "2026-10-01", ["田中さんに次回日程を聞く"])
            stored = "".join(p.read_text() for p in root.rglob("*") if p.is_file())
            self.assertNotIn("田中", stored)
            self.assertNotIn("うーん", stored)  # counterpart quote dropped
            self.assertIn("いかがでしょうか", stored)  # own quote kept
            self.assertIn("社外1", stored)

    def test_export_import_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._run(root, "2026-10-01", ["冒頭で目的を言う"])
            block = learnings.render(learnings.load_state(root), "ja")
            restored = learnings.parse_block(block)
            self.assertEqual([a["id"] for a in restored["actions"]], ["A-20261001-1"])
            self.assertEqual(restored["habits"]["conclusion_late"]["count"], 1)
            self.assertEqual(restored["worked"][0]["text"], "冒頭で名乗った")


class PrepareModeTest(unittest.TestCase):
    PAGE = """<html><head><title>山田 花子 | Example Inc.</title><script>var x=1</script></head>
    <body><header><nav>menu</nav></header><main><h1>People</h1><p>Example Inc.</p><h2>山田 花子</h2>
    <p>2015年入社<br>営業から企画へ異動。</p><h3>Q</h3><p>入社理由は？</p><p>挑戦できる環境だから。</p>
    <h2>More</h2><p>別の社員 太郎</p></main><footer>c</footer></body></html>"""

    def test_fetch_profile_text_and_stop_at(self):
        t = fetch_profile.to_text(self.PAGE, ["More"])
        self.assertIn("## 山田 花子", t)
        self.assertIn("営業から企画へ異動。", t)
        self.assertNotIn("別の社員", t)
        self.assertNotIn("var x", t)
        self.assertNotIn("menu", t)

    def test_prep_save_scrubs_names_and_find_by_date(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            rec = learnings.prep_save({"date": "2026-10-09", "language": "ja", "meeting_type": "one-on-one",
                                       "my_position": "report", "goal": "山田さんに異動の決め手を聞く",
                                       "scheduled_minutes": 30, "intents": ["山田 花子さんの今の課題を聞く"],
                                       "counterpart_names": ["山田 花子"], "counterpart_role": "manager"}, CFG, root)
            stored = (root / "prep" / f"{rec['id']}.json").read_text()
            self.assertNotIn("山田", stored)
            self.assertNotIn("花子", stored)
            self.assertEqual(learnings.prep_find(root, "2026-10-09")["id"], "P-20261009-1")
            self.assertEqual(learnings.prep_find(root, "2026-10-11")["id"], "P-20261009-1")  # within 3 days
            self.assertIsNone(learnings.prep_find(root, "2026-10-20"))
            self.assertIsNone(learnings.prep_find(root, "2026-10-08"))  # a plan is never for an earlier meeting

    def test_review_closes_the_plan(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            rec = learnings.prep_save({"date": "2026-10-02", "language": "ja", "meeting_type": "one-on-one",
                                       "my_position": "report", "goal": "予算の判断をもらう", "scheduled_minutes": 30,
                                       "intents": ["今期の期待値を聞く", "予算の判断時期を聞く"]}, CFG, root)
            t = parse_file("ja-1on1-plain.txt")
            m = {**meta("ja-1on1-plain.meta.json"), "prep_id": rec["id"]}
            rub = CFG["rubrics"]["one-on-one/report"]
            j = {"criteria": [{"id": k, "level": 3, "evidence": [{"i": 7, "quote": "今期の期待値を確認させてください"}]}
                              for k in list(rub["meeting"]) + list(rub["self"])],
                 "plan_check": [{"intent": "今期の期待値を聞く", "asked": True,
                                 "evidence": [{"i": 7, "quote": "今期の期待値を確認させてください"}]},
                                {"intent": "予算の判断時期を聞く", "asked": True,
                                 "evidence": [{"i": 5, "quote": "いつ頃までにお返事をいただけそうでしょうか"}]}]}
            self.assertTrue(verify_evidence.verify(j, t)["ok"])
            learnings.save(j, score.compute(j, m, None, CFG), t, m, CFG, root)
            self.assertTrue(json.loads((root / "prep" / f"{rec['id']}.json").read_text())["reviewed"])
            hist = json.loads((root / "history.jsonl").read_text().splitlines()[-1])
            self.assertEqual(hist["plan_coverage"], 1.0)
            self.assertIsNone(learnings.prep_find(root, "2026-10-02"))

    def test_summary_orders_habits(self):
        state = {"habits": {"a_x": {"label": "A", "count": 1, "last_seen": "2026-10-01"},
                            "b_y": {"label": "B", "count": 3, "last_seen": "2026-10-02"}},
                 "actions": [{"id": "A-1", "text": "t", "created": "2026-10-01", "meeting_type": "external",
                              "status": "open", "checks": []}], "worked": []}
        sm = learnings.summary(state)
        self.assertEqual([h["id"] for h in sm["habits"]], ["b_y", "a_x"])
        self.assertEqual(sm["open_actions"][0]["id"], "A-1")


class FollowUpFixesTest(unittest.TestCase):
    """Cases from the prepare-mode run-throughs on 2026-10-08."""

    def test_plan_check_needs_matching_evidence_kind(self):
        t = parse_file("ja-1on1-plain.txt")
        bad = {"plan_check": [{"intent": "x", "asked": True, "evidence": [{"absence": "none", "range": [0, 3]}]},
                              {"intent": "y", "asked": False, "evidence": [{"i": 7, "quote": "今期の期待値を確認させてください"}]}]}
        res = verify_evidence.verify(bad, t)
        self.assertEqual(sum("plan_check" in f and "needs" in f for f in res["failures"]), 2)

    def test_config_follows_store(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.json").write_text('{"org_pack": "/tmp/x.md"}')
            self.assertEqual(load_config(None, d)["org_pack"], "/tmp/x.md")

    def test_stock_phrases_survive_in_actions(self):
        t = parse_file("ja-1on1-plain.txt")
        san = learnings.Sanitizer(t, meta("ja-1on1-plain.meta.json"), "ja", CFG)
        out = san.clean("『難しい』『相談させて』と返されたら期日を聞く")
        self.assertIn("難しい", out)
        self.assertIn("相談させて", out)

    def test_coverage_uses_plan_count(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            rec = learnings.prep_save({"date": "2026-10-02", "language": "ja", "meeting_type": "one-on-one",
                                       "my_position": "report", "goal": "g", "scheduled_minutes": 30,
                                       "intents": ["a", "b", "c", "d"]}, CFG, root)
            t = parse_file("ja-1on1-plain.txt")
            m = {**meta("ja-1on1-plain.meta.json"), "prep_id": rec["id"]}
            j = {"criteria": [], "plan_check": [{"intent": "a", "asked": True, "evidence": [{"i": 7, "quote": "今期の期待値を確認させてください"}]}]}
            res = learnings.save(j, score.compute(j, m, None, CFG), t, m, CFG, root)
            hist = json.loads((root / "history.jsonl").read_text().splitlines()[-1])
            self.assertEqual(hist["plan_coverage"], 0.25)
            self.assertTrue(any("plan has 4 aims" in w for w in res["warnings"]))


class InferredSpeakersTest(unittest.TestCase):
    def test_assign_drop_and_flag(self):
        t = parse_transcript.parse("メモ: 要約\nこんにちは、今日はよろしくお願いします\n音楽事業について説明します\n質問してもいいですか\nどうぞ\n")
        res = assign_speakers.assign(t, {"drop": [[0, 0, "notes"]], "ranges": [[1, 1, "Me"], [2, 2, "Aki"], [3, 3, "Me"], [4, 4, "Aki"]]})
        self.assertEqual(res["speakers"], ["Me", "Aki"])
        self.assertTrue(res["speakers_inferred"])
        self.assertEqual([u["i"] for u in res["utterances"]], [0, 1, 2, 3])
        m = metrics.compute(res, {"me": "Me"}, CFG)
        self.assertTrue(m["quality"]["speakers_inferred"])
        rub = CFG["rubrics"]["one-on-one/report"]
        lv = {k: 4 for k in list(rub["meeting"]) + list(rub["self"])}
        r = score.compute(judgement(lv), {"meeting_type": "one-on-one", "my_position": "report"}, m, CFG)
        self.assertTrue(r["self"]["low_confidence"])
        self.assertFalse(r["meeting"]["low_confidence"])
        self.assertIn("話者を文脈から推定", score.to_markdown(r, "ja"))

    def test_bad_ranges_are_errors(self):
        t = parse_file("ja-1on1-plain.txt")
        self.assertIn("utterance 1 assigned twice", assign_speakers.assign(t, {"ranges": [[0, 1, "A"], [1, 2, "B"]]})["errors"])
        t = parse_file("ja-1on1-plain.txt")
        self.assertTrue(assign_speakers.assign(t, {"ranges": [[0, 99, "A"]]})["errors"])
        self.assertTrue(assign_speakers.assign(t, {"ranges": [[0, 1]]})["errors"])


class PublishReviewTest(unittest.TestCase):
    """Cases from the pre-publication adversarial review on 2026-10-08."""

    def _save(self, t, m, j, root):
        return learnings.save(j, score.compute(j, m, None, CFG), t, m, CFG, root)

    def test_aliases_and_name_in_habit_id(self):
        text = "Taro Tanaka: 今日はよろしくお願いします\nSam Lee: 田中さん、では始めましょう\nTaro Tanaka: はい\nSam Lee: 田中さんの案でいきます\n"
        t = parse_transcript.parse(text, "ja")
        m = {"meeting_type": "meeting", "me": "Sam Lee", "relationships": {"Taro Tanaka": "peer"},
             "aliases": {"Taro Tanaka": ["田中"]}, "date": "2026-10-01", "language": "ja"}
        j = {"criteria": [], "next_actions": [{"text": "田中さんに日程を聞く"}],
             "habits": [{"id": "tanaka_hedge_accepted", "label": "x"}]}
        with tempfile.TemporaryDirectory() as d:
            res = self._save(t, m, j, Path(d))
            stored = "".join(p.read_text() for p in Path(d).rglob("*") if p.is_file())
            self.assertNotIn("田中", stored)
            self.assertNotIn("tanaka", stored.lower())
            self.assertTrue(any("not a generic" in w for w in res["warnings"]))

    def test_verbatim_fragments_removed(self):
        t = parse_file("en-team-meeting.vtt")
        san = learnings.Sanitizer(t, meta("en-team-meeting.meta.json"), "en", CFG)
        out = san.clean("Follow up so Jordan can report back by Thursday with the account manager")
        self.assertNotIn("report back by Thursday", out)
        tj = parse_file("ja-external-meet.txt")
        sj = learnings.Sanitizer(tj, meta("ja-external-meet.meta.json"), "ja", CFG)
        self.assertNotIn("切り替えの手間が", sj.clean("相手の切り替えの手間がちょっと気になるという点に事例で返す"))

    def test_inferred_speakers_store_no_quotes(self):
        t = parse_transcript.parse("自己紹介します、佐藤です\n音楽事業について説明します\n質問してもいいですか\nどうぞ\n")
        t = assign_speakers.assign(t, {"ranges": [[0, 0, "Me"], [1, 1, "Aki"], [2, 2, "Me"], [3, 3, "Aki"]]})
        m = {"meeting_type": "one-on-one", "my_position": "report", "me": "Me", "date": "2026-10-01", "language": "ja"}
        rub = CFG["rubrics"]["one-on-one/report"]
        j = {"criteria": [{"id": k, "level": 2, "evidence": [{"i": 0, "quote": "自己紹介します、佐藤です"}]}
                          for k in list(rub["meeting"]) + list(rub["self"])]}
        with tempfile.TemporaryDirectory() as d:
            self._save(t, m, j, Path(d))
            self.assertNotIn("佐藤です", "".join(p.read_text() for p in Path(d).rglob("*.md")))

    def test_path_traversal_rejected(self):
        t = parse_file("ja-1on1-plain.txt")
        with tempfile.TemporaryDirectory() as d:
            for bad in ({"date": "../../x"}, {"date": "2026-10-01", "prep_id": "../../package"}):
                m = {**meta("ja-1on1-plain.meta.json"), **bad}
                with self.assertRaises(ValueError):
                    self._save(t, m, {"criteria": []}, Path(d))
            with self.assertRaises(ValueError):
                learnings.prep_save({"date": "2026/10/01", "meeting_type": "meeting"}, CFG, Path(d))
            with self.assertRaises(ValueError):
                learnings.prep_save({"date": "2026-10-01", "meeting_type": "../x"}, CFG, Path(d))

    def test_block_carries_open_plans(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            rec = learnings.prep_save({"date": "2026-10-09", "language": "ja", "meeting_type": "one-on-one",
                                       "my_position": "report", "goal": "判断材料を得る", "scheduled_minutes": 30,
                                       "intents": ["新卒に任される仕事を聞く", "次の一歩を決める"]}, CFG, root)
            block = learnings.render(learnings.load_state(root), "ja", learnings.open_preps(root))
            back = learnings.parse_block(block)
            self.assertEqual(back["preps"][0]["id"], rec["id"])
            self.assertEqual(back["preps"][0]["intents"], ["新卒に任される仕事を聞く", "次の一歩を決める"])
            self.assertEqual(back["preps"][0]["scheduled_minutes"], 30)

    def test_docx_and_pdf_get_a_clear_message(self):
        for magic in (b"PK\x03\x04rest", b"%PDF-1.7"):
            with self.assertRaises(SystemExit) as cm:
                parse_transcript.read_text(magic)
            self.assertIn(".txt", str(cm.exception))


class AudioTest(unittest.TestCase):
    """transcribe.from_whisper_json: the part that runs without a speech model."""

    WHISPER = {"language": "ja", "segments": [
        {"start": 0.0, "end": 9.76, "text": "今日は予算について相談させてください。いかがでしょうか?", "no_speech_prob": 0.01, "avg_logprob": -0.2},
        {"start": 14.42, "end": 20.48, "text": "うーん、ちょっと難しいかもしれないですね。", "no_speech_prob": 0.02, "avg_logprob": -0.3},
        {"start": 30.0, "end": 31.0, "text": "ご視聴ありがとうございました", "no_speech_prob": 0.1, "avg_logprob": -0.4},
        {"start": 40.0, "end": 41.0, "text": "おやすみ", "no_speech_prob": 0.9, "avg_logprob": -1.5},
        {"start": 400.0, "end": 402.8, "text": "来週の火曜日までに返します", "no_speech_prob": 0.01, "avg_logprob": -0.2},
    ]}

    def test_conversion(self):
        t = transcribe.from_whisper_json(self.WHISPER, None, 403.0)
        self.assertEqual(t["source"], "audio")
        self.assertEqual(t["language"], "ja")
        self.assertEqual(len(t["utterances"]), 3)
        self.assertEqual({r["reason"] for r in t["removed"]}, {"no_speech", "asr_hallucination"})
        self.assertEqual(t["duration_sec"], 403.0)
        self.assertEqual(t["duration_source"], "audio_length")
        self.assertIsNone(t["fillers_preserved"])
        self.assertFalse(t["has_speakers"])
        self.assertEqual(t["gaps"][0]["kind"], "silence")
        self.assertEqual(t["timestamp_granularity"], "utterance")

    def test_silence_after_question_is_measured(self):
        t = transcribe.from_whisper_json(self.WHISPER, "ja", 403.0)
        t = assign_speakers.assign(t, {"ranges": [[0, 0, "Me"], [1, 1, "Boss"], [2, 2, "Boss"]]})
        m = metrics.compute(t, {"me": "Me"}, CFG)
        self.assertEqual(m["silences_after_my_questions"][0]["gap_sec"], 4.7)

    def test_missing_engine_message(self):
        orig = transcribe.shutil.which
        transcribe.shutil.which = lambda _name: None
        try:
            with self.assertRaises(SystemExit) as cm:
                transcribe.find_engine("auto")
        finally:
            transcribe.shutil.which = orig
        self.assertIn("mlx-whisper", str(cm.exception))


class CalibrationFixesTest(unittest.TestCase):
    """Cases from calibrating on the user's own meetings, 2026-10-13."""

    def test_half_point_rounds_up(self):
        rub = CFG["rubrics"]["one-on-one/report"]
        lv = dict(zip(rub["meeting"], [2, 3, 2, 3, 2]))  # 7.5 + 15 + 12.5 + 7.5 + 15 = 57.5
        lv.update({k: 2 for k in rub["self"]})
        r = score.compute(judgement(lv), {"meeting_type": "one-on-one", "my_position": "report"}, None, CFG)
        self.assertEqual(r["meeting"]["score"], 58)

    def test_short_fragments_are_not_stacked_questions(self):
        t = parse_transcript.parse("A: 8人か?本当ですか?\nB: はい\nA: 予算は増やせますか?いつまでに決まりますか?\nB: 来週です\n")
        m = metrics.compute(t, {"me": "A"}, CFG)
        self.assertEqual([x["i"] for x in m["my_stacked_questions"]], [2])

    def test_isshun_is_not_a_hedge(self):
        t = parse_transcript.parse("A: 一旦整理すると、予算の話です\nB: どうしようかな\nA: はい\nB: うん\n")
        phrases = [h["phrase"] for h in metrics.compute(t, {"me": "A"}, CFG)["hedge_candidates"]]
        self.assertNotIn("一旦", phrases)
        self.assertIn("どうしようかな", phrases)

    def test_screen_share_speaker_dropped(self):
        t = parse_transcript.parse("📖 文字起こし\n00:00:00\nA: はじめます\nB's Presentation: スライドの音声\nB: よろしく\nA: では\n")
        self.assertEqual(t["speakers"], ["A", "B"])
        self.assertEqual(t["removed"][0]["reason"], "screen_share")

    def test_older_review_keeps_last_seen(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            t = parse_file("ja-1on1-plain.txt")
            for date in ("2026-10-08", "2026-09-10"):
                m = {**meta("ja-1on1-plain.meta.json"), "date": date}
                j = {"criteria": [], "habits": [{"id": "conclusion_late", "label": "x"}]}
                learnings.save(j, score.compute(j, m, None, CFG), t, m, CFG, root)
            h = json.loads((root / "learnings.json").read_text())["habits"]["conclusion_late"]
            self.assertEqual((h["first_seen"], h["last_seen"], h["count"]), ("2026-09-10", "2026-10-08", 2))

    def test_closing_window_is_last_fifth(self):
        lines = [f"A: 話{k}です" if k % 2 else f"B: 返事{k}です" for k in range(40)]
        lines[28] = "B: では木曜までに資料を送ります"  # 30% from the end: outside the last fifth
        lines[-1] = "A: よろしくお願いします"
        m = metrics.compute(parse_transcript.parse("\n".join(lines) + "\n"), {"me": "A"}, CFG)
        self.assertEqual(m["closing"]["range"], [32, 39])
        self.assertTrue(m["closing"]["closing_phrase_only"])


class ConsistencyTest(unittest.TestCase):
    def test_every_criterion_has_anchor_and_labels(self):
        anchors = set(re.findall(r"^### (\w+)", (SKILL / "references/rubrics/criteria.md").read_text(), re.M))
        used = {cid for r in CFG["rubrics"].values() for track in r.values() for cid in track}
        self.assertEqual(used, anchors)
        for lang in ("ja", "en"):
            labels = load_locale(lang)["labels"]["criteria"]
            self.assertEqual(set(labels), anchors, lang)

    def test_type_files_exist_for_every_rubric(self):
        for key in CFG["rubrics"]:
            self.assertTrue((SKILL / "references/rubrics" / f"{key.split('/')[0]}.md").is_file(), key)

    def test_locales_share_keys(self):
        ja, en = load_locale("ja"), load_locale("en")
        self.assertEqual(set(ja) - {"question_endings"}, set(en) - {"question_starts"})
        self.assertEqual(set(ja["labels"]), set(en["labels"]))

    def test_load_config_defaults(self):
        self.assertIn("rubrics", load_config())



class AdversarialRegressionTest(unittest.TestCase):
    """Cases found by the adversarial review on 2026-10-07."""

    def _save(self, t, m, j, root):
        s_ = score.compute(j, m, None, CFG)
        return learnings.save(j, s_, t, m, CFG, root)

    def _crit(self, evidence, reason="", rub="external"):
        ids = list(CFG["rubrics"][rub]["meeting"]) + list(CFG["rubrics"][rub]["self"])
        return [{"id": k, "level": 2, "reason": reason, "evidence": evidence} for k in ids]

    # --- privacy
    def test_neighbour_quote_of_counterpart_not_stored(self):
        t = parse_file("ja-1on1-plain.txt")
        m = meta("ja-1on1-plain.meta.json")
        j = {"criteria": self._crit([{"i": 5, "quote": "来週火曜までに部長に確認して返すよ"}], rub="one-on-one/report")}
        self.assertFalse(verify_evidence.verify(j, t)["ok"])
        with tempfile.TemporaryDirectory() as d:
            self._save(t, m, j, Path(d))
            stored = "".join(p.read_text() for p in Path(d).rglob("*") if p.is_file())
            self.assertNotIn("部長に確認", stored)

    def test_no_speaker_transcript_stores_no_quotes(self):
        t = parse_transcript.parse("相手の秘密の話です\n自分の話です\n最後の話です\n")
        m = {"meeting_type": "external", "me": None, "language": "ja", "date": "2026-10-01"}
        j = {"criteria": self._crit([{"i": 0, "quote": "相手の秘密の話"}])}
        with tempfile.TemporaryDirectory() as d:
            self._save(t, m, j, Path(d))
            stored = "".join(p.read_text() for p in Path(d).rglob("*") if p.is_file())
            self.assertNotIn("秘密", stored)

    def test_reason_not_stored_and_free_text_scrubbed(self):
        t = parse_file("ja-external-meet.txt")
        m = {**meta("ja-external-meet.meta.json"), "date": "2026-10-01"}
        j = {"criteria": self._crit([{"i": 6, "quote": "いかがでしょうか"}], reason="田中さんが『社長が反対』と言った"),
             "next_actions": [{"text": "「切り替えの手間がちょっと気になります」には事例で返す"},
                              {"text": "「前向きに検討します」には期日を聞く"}],
             "habits": [{"id": "tanaka-pushback", "label": "田中さんの反論を流す"}],
             "worked": ["田中さんの「今は別のシステムを使っているので」に共感した"]}
        with tempfile.TemporaryDirectory() as d:
            self._save(t, m, j, Path(d))
            stored = "".join(p.read_text() for p in Path(d).rglob("*") if p.is_file())
            self.assertNotIn("社長が反対", stored)
            self.assertNotIn("切り替えの手間", stored)
            self.assertNotIn("別のシステム", stored)
            self.assertNotIn("田中", stored)
            self.assertNotIn("tanaka-pushback", stored)
            self.assertIn("前向きに検討します", stored)  # generic hedge phrase is a pattern, not a quote

    def test_other_names_redacted(self):
        t = parse_file("ja-1on1-plain.txt")
        m = {**meta("ja-1on1-plain.meta.json"), "other_names": ["ザキ", "鈴木"]}
        san = learnings.Sanitizer(t, m, "ja", CFG)
        self.assertNotIn("ザキ", san.clean("ザキさんと鈴木さんに確認する"))

    def test_spaced_and_short_names_redacted(self):
        names = {"田中 太郎": "社外1", "Li Na": "External1"}
        out = learnings.redact("田中さんと太郎さん、li na and Li said", names)
        for w in ("田中", "太郎", "Li", "li na"):
            self.assertNotIn(w, out)

    # --- verify
    def test_negation_and_tiny_fragments_rejected(self):
        t = parse_transcript.parse("A: I disagree with that plan, it will not work.\nB: ok then\nA: fine\n", "en")
        bad = [{"i": 0, "quote": "agree with that plan"}, {"i": 0, "quote": "it will…work"}]
        for e in bad:
            self.assertFalse(verify_evidence.verify({"criteria": [{"id": "x", "level": 1, "evidence": [e]}]}, t)["ok"], e)
        tj = parse_file("ja-1on1-plain.txt")
        for q in ("す", "二…万…円…理…由"):
            res = verify_evidence.verify({"criteria": [{"id": "x", "level": 1, "evidence": [{"i": 3, "quote": q}]}]}, tj)
            self.assertFalse(res["ok"], q)

    def test_malformed_evidence_reports_failure(self):
        t = parse_file("ja-1on1-plain.txt")
        res = verify_evidence.verify({"criteria": [{"id": "x", "level": 1, "evidence": ["just a string"]}],
                                      "signals": ["oops"]}, t)
        self.assertFalse(res["ok"])

    # --- parse
    def test_vtt_without_blank_lines_or_header(self):
        vtt = ("intro line\n1\n00:00:01.000 --> 00:00:03.000\nA: one\n"
               "2\n00:00:04.000 --> 00:00:06.000\nB: two\n\n3\n00:00:07,000 --> 00:00:08,000\nA: three\n")
        t = parse_transcript.parse(vtt, "en")
        self.assertEqual(t["source"], "vtt")
        self.assertEqual([u["speaker"] for u in t["utterances"]], ["A", "B", "A"])

    def test_vtt_two_voices_and_backwards_cues(self):
        vtt = ("WEBVTT\n\n00:00:01.000 --> 00:00:09.000\n<v A>hello</v> <v B>hi there</v>\n\n"
               "00:00:20.000 --> 00:00:22.000\n<v A>later</v>\n\n00:00:01.000 --> 00:00:02.000\n<v B>late cue</v>\n")
        t = parse_transcript.parse(vtt, "en")
        self.assertIn("B", [u["speaker"] for u in t["utterances"][:2]])
        self.assertEqual(t["duration_sec"], 22)

    def test_meet_title_header_variant(self):
        text = "📖 文字起こし\n10月 15, 2026\n定例: 予算レビュー - 文字起こし\n00:00:00\n \nA: はじめます\nB: はい、お願いします\n"
        t = parse_transcript.parse(text)
        self.assertEqual(t["speakers"], ["A", "B"])
        self.assertEqual(t["utterances"][0]["text"], "はじめます")

    def test_timestamp_without_space_and_heading_labels(self):
        text = "[00:00:05]山本: 始めよう\n[00:00:09]佐藤: はい\n山本: 次\n佐藤: 了解です\n注意: 価格は税別です\n"
        t = parse_transcript.parse(text)
        self.assertEqual(t["speakers"], ["山本", "佐藤"])
        self.assertEqual(t["utterances"][0]["start"], 5)

    def test_names_with_periods_and_inner_bom(self):
        text = "Lee: hi\nDr. Kim: hello\nLee: ok\nDr. Kim: bye\n﻿Lee: end\n"
        t = parse_transcript.parse(text, "en")
        self.assertEqual(t["speakers"], ["Lee", "Dr. Kim"])

    def test_plain_gap_is_estimated(self):
        t = parse_file("ja-1on1-plain.txt")
        self.assertEqual(len(t["gaps"]), 1)
        self.assertEqual(t["gaps"][0]["kind"], "estimated")
        self.assertEqual(t["gaps"][0]["to_sec"], 24 * 60 + 50)

    def test_plain_long_monologue_is_not_a_gap(self):
        text = ("[00:00:00] A: " + "あ" * 1800 + "\n[00:06:25] B: はい\n[00:06:30] A: 続けます\n"
                "[00:06:35] B: うん\n[00:06:40] A: 了解\n")
        self.assertEqual(parse_transcript.parse(text)["gaps"], [])

    def test_encodings(self):
        raw = "山本: 始めよう\n佐藤: はい\n山本: 次\n佐藤: 了解\n"
        for enc in ("cp932", "utf-16"):
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "x.txt"
                p.write_bytes(raw.encode(enc))
                self.assertEqual(parse_transcript.parse(parse_transcript.read_text(p))["speakers"], ["山本", "佐藤"], enc)

    # --- score
    def test_duplicate_or_missing_ids_are_errors(self):
        j = {"criteria": [{"id": "purpose_shared", "level": 0}, {"id": "purpose_shared", "level": 4}, {"level": 2}, {"id": "zzz", "level": 1}]}
        r = score.compute(j, {"meeting_type": "external"}, None, CFG)
        self.assertGreaterEqual(len(r["errors"]), 3)

    def test_overrun_not_pre_rounded_and_meta_override_wins(self):
        m = {"meeting_type": "external", "scheduled_minutes": 7, "actual_minutes": 7.7035}
        lv = {k: 4 for k in list(CFG["rubrics"]["external"]["meeting"]) + list(CFG["rubrics"]["external"]["self"])}
        r = score.compute(judgement(lv), m, None, CFG)
        self.assertEqual(r["meeting"]["score"], 95)
        stale = {"duration": {"overrun_ratio": 0.839}}
        r = score.compute(judgement(lv), {"meeting_type": "external", "scheduled_minutes": 30, "actual_minutes": 32}, stale, CFG)
        self.assertEqual(r["meeting"]["score"], 100)

    def test_invalid_times_and_missing_position(self):
        lv = {k: 4 for k in list(CFG["rubrics"]["external"]["meeting"]) + list(CFG["rubrics"]["external"]["self"])}
        r = score.compute(judgement(lv), {"meeting_type": "external", "scheduled_minutes": 0, "actual_minutes": 10}, None, CFG)
        self.assertTrue(r["errors"])
        r = score.compute(judgement({}), {"meeting_type": "one-on-one"}, None, CFG)
        self.assertTrue(r["errors"])

    def test_half_up_rounding(self):
        self.assertEqual(score.round_half_up(62.5), 63)
        self.assertEqual(score.round_half_up(87.5), 88)

    # --- learnings
    def test_not_applicable_check_is_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            t = parse_file("ja-external-meet.txt")
            m = {**meta("ja-external-meet.meta.json"), "date": "2026-10-01"}
            r1 = self._save(t, m, {"criteria": self._crit([{"i": 6, "quote": "いかがでしょうか"}]),
                                   "next_actions": [{"text": "冒頭で目的を言う"}]}, root)
            aid = r1["new_action_ids"][0]
            m2 = {**m, "date": "2026-10-02"}
            self._save(t, m2, {"criteria": self._crit([{"i": 6, "quote": "いかがでしょうか"}]),
                               "previous_actions_check": [{"id": aid, "done": None, "note": "not applicable"}]}, root)
            a = json.loads((root / "learnings.json").read_text())["actions"][0]
            self.assertEqual(a["checks"], [{"date": "2026-10-02", "done": None, "note": "not applicable"}])

if __name__ == "__main__":
    unittest.main()
