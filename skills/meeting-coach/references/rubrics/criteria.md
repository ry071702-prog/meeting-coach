# Criteria and level anchors

Every criterion is judged on a 0–4 scale or `null`. Each level is written as something you can point to in the transcript, so two judges reading the same text should land on the same level.

**How to pick a level**: read the levels from 4 downward and stop at the first one that is true of the meeting as a whole. Levels 2–0 describe failures: if the failure described at level *k* clearly happened at a moment that mattered (the ask, the decision, the close), the level cannot be higher than *k*.

- `null` means *not scorable from this input* (for example no speaker labels, or the topic never came up). It is removed from the denominator. Do not use `null` to avoid a low score.
- Every non-null level needs at least one evidence item: a verbatim quote with its utterance index `i`, or an `absence` with the utterance `range` where the thing should have happened.
- When behaviour differs across the meeting, weigh the moments that mattered most for its purpose (the ask, the decision, the close) over minor ones, and mention the variation in `reason`.
- Metrics are inputs, not verdicts. A hedge followed by an owner and a date is fine. A short "はい" can be real agreement.
- Judge **the user's behaviour** on the `self` track. Other people's behaviour is evidence about how the user's words landed, never a score of those people.

Which criteria apply, and their weights, depend on the meeting type: see `meeting.md`, `one-on-one.md`, `external.md`. Weights live in `config.default.json`.

---

## Meeting track

### purpose_shared
Was the purpose or desired outcome said out loud near the start? "Near the start" means before the first topic is discussed in depth (as a rule of thumb, within the first tenth of the meeting). With several agenda items, judge whether the overall outcome was stated, not only the first item: stating only the first item is at most 3.
- **4** Within the first few minutes someone states what this meeting should produce (a decision, a plan, an agreement), and others acknowledge it.
- **3** The purpose is stated early but only as a topic ("today is about X"), not as an outcome.
- **2** The purpose becomes clear only midway, or only implicitly.
- **1** Participants show confusion about why they are here ("what did we want to decide?").
- **0** No purpose is ever stated and the discussion wanders.

### discussion_focus
Did the discussion stay on what the meeting was for?
- **4** Topics follow the purpose; digressions are noticed and parked ("let's take that offline").
- **3** One or two digressions, eventually brought back.
- **2** Long digressions that eat a visible share of the time.
- **1** The main topic is reached late or only partially.
- **0** The stated purpose is never really discussed.

### decisions_clear
Are outcomes clear: **what** was decided, **who** does it, **by when**?
- **4** Each outcome has an owner and a date, and someone recaps them at the end.
- **3** Owners and dates for most outcomes; no recap, or a recap with gaps.
- **2** Outcomes are mentioned but owners or dates are missing ("let's look into it").
- **1** Only vague closings ("thanks, let's keep going", 「よろしくお願いします」で終わる).
- **0** Nothing is decided, and that was not the intent.
- Use `metrics.closing` and `metrics.hedge_candidates` (`followed_by_commitment`) as starting points.

### participation_balance
Did the people who needed to speak get to speak? (`null` without speaker labels.) There is no target percentage: judge against the purpose. A report in a 1:1 should hold enough of the talk to bring their own topics; a facilitator naturally talks more.
- **4** Share of talk matches the meeting's purpose (see the type file); quieter people are invited in.
- **3** Mostly balanced; one person a little dominant.
- **2** One person dominates beyond what the purpose needs; others mostly backchannel.
- **1** A key participant barely speaks in substance.
- **0** Effectively a monologue when it should have been a conversation.

### goal_achieved
Did the meeting achieve **what the user said they wanted** (`meta.goal`)? `null` if the user gave no goal.
- **4** Fully achieved, with an explicit confirmation in the transcript.
- **3** Mostly achieved; a minor part left open with a clear next step.
- **2** Partly achieved; the important part is still open.
- **1** Barely moved toward the goal.
- **0** Not achieved, or moved away from it.

---

## Self track (the user's own behaviour)

### conclusion_first
Does the user lead with the point (request, conclusion, question) before background?
- **4** Most substantial turns open with the point in the first one or two sentences.
- **3** Usually point first; a few long wind-ups.
- **2** The point often comes after long background (`metrics.my_long_turns` with the ask at the end).
- **1** Listeners have to ask "so what do you need?" / 「つまり？」.
- **0** The point is never stated clearly.

### questioning_listening
Does the user ask and then let the other person talk?
- **4** Open questions, waits for full answers, follows up on what was said. Talk share fits the type.
- **3** Good questions but sometimes cuts in or answers them.
- **2** Few real questions, or stacks several in one breath (`metrics.my_stacked_questions`), or asks then keeps talking (`metrics.my_question_then_kept_talking`).
- **1** Mostly telling; questions are rhetorical.
- **0** No questions at all where the type needs them.

### understanding_check
Does the user verify that the message landed, instead of assuming?
- **4** Asks the other person to restate, or checks understanding with a specific question ("which part is unclear?" / 「どこが一番引っかかりますか」), and adjusts.
- **3** Checks with a generic "does that make sense?" / 「大丈夫ですか」 and gets a substantive answer.
- **2** Checks only generically and accepts a bare "yes" / 「はい」.
- **2** Never checks, but the other side's replies show the message landed (they restate, ask a relevant question, or build on it) — the user gets no credit for checking, but nothing went wrong.
- **1** Never checks, and replies after long explanations are thin or off-target (`metrics.thin_responses`).
- **0** Moves on despite visible confusion.
- Scope: a thin reply right after the user's own explanation belongs here. A hedge or deferral in answer to a request or proposal belongs to `reaction_handling`. Do not penalise the same moment under both.

### reaction_handling
When reactions are thin or noncommittal, does the user notice and probe?
- **4** Notices a weak or hedged reaction ("let me think" / 「検討します」 / bare 「はい」) and asks a concrete follow-up that turns it into a real answer or a dated next step.
- **3** Notices and probes once, partly resolved.
- **2** Notices but lets it go ("OK, think about it").
- **1** Does not notice; continues as if agreed.
- **0** Treats a hedge as a yes and builds on it.
- If the user says the counterpart is **habitually quiet** (`meta.counterpart_reserved`), a short backchannel alone is not evidence of a problem; only score down for unresolved hedges or missed questions.
- In scope: hedges, deferrals ("let me take it back", 「一度ボールを預からせて」), conditional answers that leave the decision open (「反応見てから」), and answers with an owner but no date. Out of scope: a clear, substantive objection — that is a real answer; judge how the user engaged with it under `questioning_listening` or `discovery`.
- If nothing in scope happened, the level is `null`.

### next_action_ownership
Does the user leave with clear next actions for themselves? With several actions, judge the one that matters most for the user's goal. An action the user proposed but nobody (including the user) took on counts as no action.
- **4** States own next actions with dates, and confirms the other side's.
- **3** Own actions clear; the other side's left implicit.
- **2** Actions mentioned without dates.
- **1** Ends with 「よろしくお願いします」 / "thanks" and nothing concrete.
- **0** The user agreed to something and it is unclear what.

---

## Type-specific criteria

### agenda_ownership  (one-on-one, user is the report)
- **4** The user brings their own topics (a question, a problem, a request) and uses the time for them.
- **3** Brings one topic; most time follows the manager's agenda.
- **2** Raises a topic only when asked "anything else?".
- **1** Has nothing to bring; the manager fills the time.
- **0** Avoids the topics they needed to raise (visible from context or `meta.goal`).

### expectation_alignment  (one-on-one, user is the report)
- **4** Asks what good looks like ("what would make this a success for you?") and restates it.
- **3** Expectations discussed and either asked for or restated, but not both.
- **2** Expectations implied, not checked.
- **1** Leaves with a different understanding than the manager expressed.
- **0** The topic of expectations is avoided when it was clearly needed.

### psychological_safety  (one-on-one, user is the manager)
- **4** Lets the other person finish, acknowledges before disagreeing, invites concerns explicitly.
- **3** Mostly safe; an occasional interruption or quick dismissal.
- **2** Frequent interruptions or "but" / 「でも」 openings that shut the topic.
- **1** Corrects or lectures when the person opens up.
- **0** The person visibly withdraws (answers shrink to backchannels after a correction).

### counterpart_ownership  (one-on-one, user is the manager)
- **4** The other person states their own next step in their own words.
- **3** The user proposes, the other person adapts it.
- **2** The user assigns; the other person only says yes.
- **1** Next steps are assigned with no check that they are feasible.
- **0** No next step for the other person.

### discovery  (external)
- **4** Learns the other side's situation, problem, who decides, and timing, with follow-up questions.
- **3** Learns most of it; one of these is missing.
- **2** Learns the problem only on the surface; mostly presents.
- **1** Presents without asking.
- **0** Misreads the other side's situation and pushes anyway.

### next_meeting_secured  (external)
- **4** A concrete next step with a date and attendees is agreed in the meeting.
- **3** Agreed next step without a date.
- **2** "We'll be in touch" with a soft commitment from the user only.
- **1** The other side's 「検討します」 / "let me think" ends the meeting without a follow-up date.
- **0** No next step at all.
