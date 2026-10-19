# Report template

Write the report in the user's language. Keep it short enough to read in two minutes. Every criticism carries a quote with its time (or utterance number when there is no time). Never invent numbers: scores, bands and coverage are copied from `score.json`, counts from `metrics.json`.

```markdown
## <date> <meeting type> — <one-line verdict>

<score table printed by `score.py --md`, pasted as is>

### Last time's actions            (only if there were open actions)
- [done / not yet / not applicable] <action> — <quote or reason>

### Against the plan               (only if a plan from prepare mode was found)
- [asked / not asked] <aim> — 「<quote>」 (<mm:ss>)
- Goal: <reached / partly / not> — <one line>

### What worked                    (1–2 items)
- <behaviour> — 「<quote>」 (<mm:ss>)

### Biggest point losses           (up to 3 from **your score**, largest weight × lost levels first; add a meeting-score loss only if the user could have prevented it)
1. **<criterion name>** <level>/4
   - What happened: <one sentence>
   - Evidence: 「<quote>」 (<mm:ss>)
   - Try instead: <the exact sentence or move to use next time>

### Did it land?                   (signals with verdict "risk" only; say "none found" if empty)
- <signal> — 「<quote>」 (<mm:ss>) — <why it may not have landed>

### Next time (1–3)
- [ ] <observable action, checkable next time>

### About this input               (only if something limited the review)
- <e.g. no speaker labels: talk share and self criteria X, Y not scored>
- <e.g. speakers were assigned from context (`speakers_inferred`): your score is indicative>
- <e.g. duration is a lower bound / estimated>
- <e.g. nothing transcribed between 03:30 and 37:40 (`quality.gaps`): a break, silence or a missing part; ask the user before treating it as meeting time>
- <e.g. last time's actions not checked because they do not apply to this meeting type>
- <e.g. quote from a line flagged as a possible transcription error>
```

Rules
- Time format: `mm:ss` from the utterance `start` (prefix `~` when `time_estimated` is true). Without timestamps use `#<i>`.
- "Try instead" must be concrete enough to say out loud. "Explain more clearly" is not acceptable.
- Do not grade or characterise the other person. Describe their reactions only as evidence about how the user's words landed.
- When `low_confidence` is true for a track, say so next to its score and keep conclusions tentative.
