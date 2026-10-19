# meeting-coach

**Prepare for a meeting, then review it — as one loop.** An Agent Skill for Claude that researches the person you are about to meet, plans what to ask, and after the meeting scores it out of 100 from the transcript with quoted evidence. What you learn is kept and comes back as reminders before your next meeting.

[日本語の README はこちら](README.ja.md)

```
 prepare ──▶ meeting ──▶ review ──▶ next prepare
   │                        │
   │ research + questions   │ two scores /100, evidence, "did it land?",
   │ reminders from history │ check against the plan, 1–3 actions
   └──────── kept locally in ~/.meeting-coach ─────────┘
```

## What you get

**Before the meeting**
- A short brief on the other person from public sources (their organisation's pages, talks, interviews), each fact with its source; for external meetings, their company's recent moves
- A career timeline and a reading of the person: what they value in their own words, what they care about now, common ground with you, what will land and what to avoid
- An opening line, 5–7 questions (rapport → core → close) tied to your goal and to their own words, and reminders picked from your past reviews
- If you give notes from an earlier meeting with them: what was agreed, what each side owes, what not to ask again

**After the meeting**
- **Meeting score /100** (how the meeting went) and **Your score /100** (how you behaved), never blended
- Every point lost is backed by a verbatim quote, or by the stretch of the meeting where something expected never came; quotes are machine-checked against the transcript. Time overrun is computed from the timestamps
- "Did it land?" signals: backchannel-only replies after your long explanations, polite deferrals that never got an owner or date ("let me think about it", 「検討します」), no questions back, vague closes — judged in context, reported as signals, not verdicts
- A check against your plan: which planned questions you actually asked
- 1–3 next actions written so they can be checked next time

### How scoring works
The model only assigns each criterion a **level 0–4 with evidence**. A script turns levels into points with fixed weights, so the same judgement always gives the same score. Time overrun lowers the meeting score, and lowers your score only if you ran the meeting. Criteria the input cannot show (for example, no speaker labels) are marked *not scorable* and dropped from the denominator instead of counting as zero. Rubrics differ for group meetings, 1:1s (as the manager, as the report, or as peers) and external meetings. All weights, bands and penalties are **design defaults, not research findings** — override any of them in `~/.meeting-coach/config.json`.

### Languages
English and Japanese, including the indirect ways a Japanese "yes" can mean "not yet". Other languages can be added as locale files.

## Install

**Claude Code**
```text
/plugin marketplace add ry071702-prog/meeting-coach
/plugin install meeting-coach@meeting-coach
```

**Claude.ai** — download `meeting-coach.zip` from [Releases](../../releases) and upload it under *Settings → Capabilities → Skills*. Claude.ai cannot keep files between chats, so the skill prints a short block at the end of each prepare and review (your habits, open actions and plans not yet reviewed); paste it at the start of the next chat. Scripts there have no network access, so profiles are read with Claude's own web tools.

**In the browser (no install)** — open the [web app](https://ry071702-prog.github.io/meeting-coach/), pick an AI under *Settings* and enter your own API key for it. It runs the same scoring scripts in your browser (via Pyodide) and calls that AI's API directly from your browser, so any usage charges are billed to your key by that AI company, and your API key and meeting content pass through no one else's server, the author's included. Scores, lessons and plans stay in that browser; use *History → Download backup* to move them.

| AI | Get a key | Default model | Tested against the real API |
|---|---|---|---|
| Claude (Anthropic) | [Claude Console](https://platform.claude.com/settings/keys) | Claude Opus 5.5 | Not yet |
| OpenAI | [OpenAI Platform](https://platform.openai.com/api-keys) | GPT-6 Astra | Not yet |
| Gemini (Google) | [Google AI Studio](https://aistudio.google.com/apikey) | Gemini Flash | Yes, on 2026-10-15 with `gemini-flash-latest` and the fictional meetings in `examples/`; experimental, as scoring again can move a meeting by one band. Preparing reads only the URLs you give and does not search the web |

Other models from the same company can be typed in by name, though a model that does not accept the app's reasoning-depth setting may be rejected by the API. Claude and OpenAI have only been run against a mock of their API so far; if one does not work for you, please open an [issue](../../issues).

> **Gemini free tier** — with a key that has no billing set up, Google uses what you send to improve its products, and people may read it ([Gemini API terms](https://ai.google.dev/gemini-api/terms)). The app shows a warning while Gemini is selected. Use a key with billing enabled for real meetings.

**Other agents that read `SKILL.md`** (Codex and similar) — copy `skills/meeting-coach` into that agent's skills folder.

Requirements: Python 3.9+ (standard library only). Web research needs a web search tool in your agent.

## Use

- *"Prepare me for my 1:1 with Alex Kim tomorrow. Here's their profile: <url>. I want to agree on my goals for next quarter."*
- *"Review this meeting"* + a transcript file or pasted text

Supported transcripts (as text files — export `.docx` or PDF notes as `.txt` first): Google Meet (Gemini notes), Zoom and Teams `.vtt`, Otter-style exports, any `Name: text` log, and plain text without speakers (speakers are then assigned from context, your score is marked indicative and no quotes are stored). **Recordings (audio or video)** are transcribed on your machine with a local Whisper (`mlx-whisper` on Apple Silicon, or `openai-whisper`) and ffmpeg; nothing is uploaded. You get real timings, so silence after your questions is measured too. Speakers are then assigned from context, so your score is indicative, and very short replies can be missed by the speech model. Not available in Claude.ai or the web app.

## Privacy
- The transcript becomes part of your conversation with the AI service you use (for example, it is uploaded to Claude.ai if you use Claude.ai). The skill's scripts send it nowhere else.
- In the web app, your API key and meeting content go from your browser straight to the AI company you picked (Anthropic, OpenAI or Google). The page and scoring scripts load from this site, and the libraries (the Python runtime, the Markdown renderer, the HTML sanitiser and the Anthropic SDK) from jsDelivr. When preparing, the other person's name, organisation and URLs go to the AI: Claude and OpenAI use them in web searches, and Gemini only reads the pages at the URLs given (we judged that the app cannot meet the terms for Gemini's Google Search grounding). Data is kept in that browser (IndexedDB) instead of `~/.meeting-coach/`; what is and is not kept is the same as below.
- What is kept in `~/.meeting-coach/`: scores, levels, your own verified quotes, your next actions and habits, and from Prepare mode the meeting goal and the aims of your questions. **Not kept:** the reviewer's reasoning, research notes, profile text, and other people's words — verbatim stretches of what others said are removed from stored text, but short fragments or paraphrases can remain.
- Other participants' names are replaced by roles. This is best effort: a third person mentioned only in passing, or a participant called by a different name than their display name (tell the skill the other spelling), can slip through.
- Research covers public, professional information only. The skill does not look up private social media, family, health, politics or similar, and checks every source against at least two identifiers to avoid mixing up people with the same name.
- Recording laws and workplace rules differ. Get consent before recording a meeting, and check your organisation's rules before giving meeting transcripts or colleagues' information to an AI tool.

## Configure

`~/.meeting-coach/config.json` overrides any key of [`config.default.json`](skills/meeting-coach/config.default.json). Useful keys:

| Key | What it does |
|---|---|
| `rubrics`, `bands`, `time_penalty` | Weights, band thresholds and overrun penalties |
| `research_budget` | Max web searches per person / company (`learnings.py config` shows the values in effect) |
| `notes_dirs` | Folders with your meeting notes, searched by name before a follow-up meeting |
| `org_pack` | Path to an organisation pack (below) |
| `redact_names` | Replace participants' names with roles in stored files (default `true`) |

### Organisation packs
An org pack is a Markdown file that tells the skill where your organisation publishes things about its people (staff pages, internal-but-public blogs, event pages) and how to read them. Keep it outside this repo and point `org_pack` at it. See [`examples/org-pack-example.md`](examples/org-pack-example.md).

## Develop
```bash
python3 -m unittest discover tests
node --test 'tests/providers/*.test.mjs'   # the web app's AI providers (Node 22+)
bash tests/e2e/run.sh                      # the web app end to end, AI APIs mocked (needs Docker)
```
Fictional example transcripts live in `examples/`. Never add real meetings to this repo.

## License
[MIT](LICENSE)
