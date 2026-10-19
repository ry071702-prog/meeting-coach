# Type: one-on-one (1on1, interview with a team member, mentoring)

Rubric keys depend on the user's position relative to the other person (`meta.my_position`):

| `my_position` | Situation | Rubric key |
|---|---|---|
| `report` | The user meets their manager / senior | `one-on-one/report` |
| `manager` | The user meets a team member / junior / new hire | `one-on-one/manager` |
| `peer` | Same level | `one-on-one/peer` |

Weights: `config.default.json → rubrics["one-on-one/<position>"]`. Level anchors: `criteria.md`.

## User is the report (`report`)
The time is the user's. Good: the user arrives with topics, says what they need first, and leaves knowing what the manager expects.
- **conclusion_first** matters: managers have little time; the ask should come first.
- **agenda_ownership** and **expectation_alignment** are added.
- A manager doing most of the talking is a sign the user did not bring enough, not a fault of the manager.

## User is the manager (`manager`)
The time is the other person's. Good: the other person talks most, feels safe raising problems, and names their own next step.
- **participation_balance** is weighted up: the other person should hold the larger share of talk. If the user holds most of it, that is the main finding.
- **psychological_safety** and **counterpart_ownership** are added; **questioning_listening** is weighted up.
- Thin answers after the user's corrections are evidence for `psychological_safety`, not a judgement of the other person.

## Peer (`peer`)
Mutual exchange. Use the default self criteria.

## Common to all
- Relationship (`meta.relationships`) changes how to read politeness: with a senior, 「なるほどですね」 and short agreement can be deference rather than agreement. Check whether a concrete commitment followed.
