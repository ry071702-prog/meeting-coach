# Org pack: Example Corp (fictional)

**Use only when** the other person works at Example Corp or one of its subsidiaries. Do not use for anyone else.

This file is an example of an organisation pack for meeting-coach. Copy it, keep it outside the repository, and set `"org_pack": "~/.meeting-coach/org/<name>.md"` in `~/.meeting-coach/config.json`. List only sources you have opened yourself and confirmed exist, with the date you checked.

## Sources (checked 2026-01-01)

| What | URL pattern | How to use |
|---|---|---|
| Staff profiles on the careers site | `https://careers.example.com/people/<id>` | Read first when the user gives the URL. Run `fetch_profile.py <url> --stop-at "More people"` — the block after that heading lists other employees |
| Company blog / owned media | `https://example.com/stories/` | Search `site:example.com/stories <name>` for interviews with the person |
| Press releases | `https://example.com/news/<id>` | Recent moves of the person's business, with dates. Context, not facts about the person |
| Event pages where staff speak | `https://events.example.org/<id>` | Speaker bios carry current titles. Search engines often miss them: ask the user for links |

Search tip: the bare name returns many people with similar names. Add the current title or the product they work on, and use the thorough search mode.

## How a staff profile is laid out
1. Company (subsidiary) name
2. Name (heading) and year joined
3. Short career summary
4. Tags: student background, job types, "changed roles"
5. Q&A (questions differ per person)
6. Works: product and role

## Turning it into questions
- Profiles are written for job seekers and are polished. Do not ask back what is already written; ask what changed since, what was hard, or how it applies now.
- "Changed roles" tag → ask why they moved and what was hardest at first.
- Latest role → ask what is hardest about it now, and what they expect from someone new.

## Do not collect
Personal social media, family, home area or anything outside the person's public professional role.
