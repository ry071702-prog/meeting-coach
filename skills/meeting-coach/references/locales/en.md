# Reading "it didn't land" signals in English meetings

`metrics.py` only finds **candidates** with word lists and counts. This file says how to judge them in context. Always report them as signals with quotes, never as certainties.

## 1. Backchannel-only replies (`thin_responses`, `listener_backchannels`)
- "Yeah", "right", "okay", "mm-hmm" mean *I'm listening*, not *I understood* or *I agree*.
- **Signal**: after a long explanation from the user (`my_long_turns`), the reply is only a backchannel or a few words, with no question, restatement or concrete reaction, and the topic moves on.
- **No signal**: the backchannel is followed by a paraphrase, a condition, an example or a question.
- If the user says the other person is habitually quiet (`counterpart_reserved`), thin replies alone are not a finding.

## 2. Polite deferral (`hedge_candidates`)
- "Let me think about it", "I'll get back to you", "sounds interesting", "let me check with the team", "maybe down the road" can mean yes-later, no, or undecided.
- **Signal** (`followed_by_commitment: false` and nothing in context): no owner, date or concrete condition follows, and the user did not probe.
- **No signal**: "I'll check with finance and get back to you by Friday."
- "That's interesting" without a follow-up question is often a soft no.

## 3. No questions from the other side (`counterpart_questions`)
- Zero questions after a short, simple update is fine. Zero questions after a long proposal suggests confusion, low interest, or that asking feels unsafe. Read it together with `understanding_check`.

## 4. Vague closing (`closing`)
- Ending on "thanks, talk soon" with no owner or date right before (`closing_phrase_only: true`) means decisions are floating. Not a problem for purely informational meetings.

## 5. The user's own delivery
- **Point last**: background first, the ask at the end.
- **Stacked questions** (`my_stacked_questions`): people answer the easier one.
- **Asking then answering** (`my_question_then_kept_talking`): the other person's real view never comes out.
- Fillers ("um", "you know") are not penalised by count; use them only when they bury the point.

## 6. Relationship changes the reading
- Senior or client: disagreement is often withheld. No objections is not proof of agreement.
- Junior or new hire: "yes" may be the only safe answer. Look for whether the user made it easy to raise concerns.

## 7. Writing next actions
Make them checkable next time: a phrase to say or an observable behaviour.
- Good: "In the first minute, say what we need to decide today." "After explaining, ask 'which part feels least clear?'" "When someone says 'let me think about it', ask 'when could you get back to me?'"
- Bad: "Communicate more clearly." "Be more empathetic."
