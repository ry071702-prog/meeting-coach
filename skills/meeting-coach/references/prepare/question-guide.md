# Designing the questions

The plan exists so the review afterwards scores well for the right reasons: purpose stated up front, real questions, understanding checked, a clear close. Questions follow three phases:

1. **Open (rapport, 1–2 questions)** — one hook from something the person made public about their work, phrased so they talk, not confirm. 「〇〇の記事で△△と書かれていましたが、今もそう感じますか」 beats 「〇〇されてたんですよね」.
2. **Core (3–4 questions)** — what the user needs from this meeting (`goal`). Open questions first, then one follow-up for each that asks for a concrete example or a number.
3. **Close (1 question)** — the other person names the next step, owner and date. 「次に私が何をしたら一番いいですか」 / "What would be the most useful next step from my side, and by when?"

Each question carries:
- `phase` (open / core / close)
- the exact wording in the meeting language
- `aim` — a short, generic description of what it is for, with **no names and no profile details** (「異動を決めた理由を聞く」, not 「〇〇さんが新規事業に移った理由」). Aims are stored and checked after the meeting.
- `basis` — the source line or URL behind it, or "goal" when it comes from the user's aim.

## By meeting kind

| Kind | `meeting_type` / `my_position` | What the questions should do |
|---|---|---|
| Your report / junior (1on1) | `one-on-one` / `manager` | Let them talk most. Ask about what is hard right now, what they want to grow into, and what they need from you. Avoid advice in the first half. End with them naming their next step. |
| Student / candidate / new hire | `one-on-one` / `manager` | Make it safe to say worries. Ask for the one thing they are most unsure about. Ask what they would need to see or hear to decide. Do not pitch before you understand their axis. |
| Your manager / a senior in another team (incl. career or placement talks) | `one-on-one` / `report` | Bring your own agenda and ask first. Ask what success looks like in their team, what new members struggle with, and how they would decide in your place. Restate what you heard before closing. |
| First meeting with a colleague | `one-on-one` / `peer` | Find the overlap between your work and theirs. Ask what they are working on now and where they could use help. Agree one concrete follow-up. |
| External (sales, client, partner) | `external` (+ `stage`) | Discovery before proposal: their situation, the problem, who decides, timing. Check each hypothesis from the company research with a question instead of asserting it. Secure a dated next step. |
| Group meeting you run | `meeting` | One sentence of purpose, the decision needed, who must speak, and the closing recap of owners and dates. |

## Use the analysis
Every core question should connect the user's goal to something in "Reading them": their values, their current focus, or what they want from the meeting. A question that quotes their own words back and asks how it applies to the user's situation ("You said X in that talk — how would that apply to someone starting in your team?") invites a real answer instead of a stock one. Show where each link comes from in the Basis column.

## Build on earlier meetings
If notes from an earlier meeting with this person were given: open by reporting back on what the user said they would do last time, then ask about what was left open. Never re-ask a question the notes show was already answered; ask what changed since instead.

## Use the user's own history
Pick 1–3 items from `learnings.py summary`:
- an open next action that fits this kind of meeting, or
- a habit with a high count that this meeting is likely to trigger (e.g. `conclusion_late` before a meeting where the user must make a request).
Turn each into a concrete reminder ("Ask the first question within the first minute"), and list the action ids as `focus_action_ids`.

With no history yet, use these defaults and leave `focus_action_ids` empty: state the purpose in the first minute; ask one question and wait for the full answer before the next; restate what you heard and confirm who does what by when before closing.

## Things to avoid writing into the plan
- Questions that show off research ("I saw your 2019 interview...") without an aim.
- Facts presented to the other person that come from inference.
- More than 7 questions; the user cannot use more in 30 minutes.
- Leading questions that only allow yes.
