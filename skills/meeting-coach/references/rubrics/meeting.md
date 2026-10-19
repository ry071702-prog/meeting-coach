# Type: meeting (regular / strategy / project / any group meeting)

Rubric key: `meeting`. Criteria and weights: `config.default.json → rubrics.meeting`. Level anchors: `criteria.md`.

## What a good one looks like
A clear outcome stated up front, discussion that stays on it, and a close where every decision has an owner and a date.

## Reading the criteria for this type
- **participation_balance**: the people whose input the decision needs should be heard. A facilitator talking more than others is normal; one person holding most of the talk while decision-makers only backchannel is not.
- **conclusion_first**: in status updates and proposals, the ask or conclusion should open the turn. Long background before the ask is the most common pattern to flag.
- **understanding_check / reaction_handling**: in group settings silence is often read as agreement. Flag places where the user proposed something, the room answered only with backchannels, and the user moved on.
- **time**: overrun is handled by `score.py` from scheduled vs actual length. Do not double-penalise it in `discussion_focus`; judge focus on content only.
