import { test } from "node:test";
import assert from "node:assert/strict";
import { citedSources, extractJSON, sourcesMarkdown } from "../../web/providers/common.js";

test("extractJSON takes the object out of a fenced reply with prose around it", () => {
  assert.deepEqual(extractJSON('Here it is:\n```json\n{"a": 1, "b": [2, {"c": 3}]}\n```\nDone.'), { a: 1, b: [2, { c: 3 }] });
});

test("extractJSON skips braces in the prose before and after the object", () => {
  assert.deepEqual(extractJSON('Fields like {name} are filled in. {"goal": "x"} See {notes}.'), { goal: "x" });
});

test("extractJSON is not fooled by braces and quotes inside strings", () => {
  assert.deepEqual(extractJSON('{"q": "use } or { and \\" here", "n": {"m": "}"}}'), { q: 'use } or { and " here', n: { m: "}" } });
});

test("extractJSON prefers the whole answer over a small example before it", () => {
  assert.deepEqual(extractJSON('Return {} when empty.\n{"intents": ["a"], "goal": "g"}'), { intents: ["a"], goal: "g" });
});

test("extractJSON takes the answer after a longer format example, and {} only when nothing else parses", () => {
  const reply = 'Use this shape: {"goal": "the goal of the meeting in one line", "intents": ["one aim per question"]}\n{"goal": "g", "intents": ["a"]}';
  assert.deepEqual(extractJSON(reply), { goal: "g", intents: ["a"] });
  assert.deepEqual(extractJSON('{"a": 1} and nothing else: {}'), { a: 1 });
  assert.deepEqual(extractJSON("Nothing was found: {}"), {});
});

test("extractJSON with the required keys takes the answer over an example or note after it", () => {
  const note = '{"goal": "g", "intents": ["a"]}\n\nNote: each intent is an object like {"id": 1}';
  assert.deepEqual(extractJSON(note, ["goal", "intents"]), { goal: "g", intents: ["a"] });
  const example = '```json\n{"goal": "g", "intents": ["a", "b"]}\n```\nAn empty plan would be {"goal": "", "intents": []}';
  assert.deepEqual(extractJSON(example, ["goal", "intents"]), { goal: "", intents: [] }); // both hold every key: the last wins
  assert.deepEqual(extractJSON('{"goal": "g"} then {"id": 1}', ["goal", "intents"]), { id: 1 }); // none holds every key
});

test("extractJSON throws when no object parses", () => {
  assert.throws(() => extractJSON("no json {here} at all {"), /did not return JSON/);
  assert.throws(() => extractJSON(""), /did not return JSON/);
});

test("citedSources lists each cited page once, in the order first cited", () => {
  assert.deepEqual(citedSources([
    { url: "https://b.example/", title: "B" },
    { url: "https://a.example/", title: "A" },
    { url: "https://b.example/", title: "B again" },
  ]), [{ url: "https://b.example/", title: "B" }, { url: "https://a.example/", title: "A" }]);
});

test("citedSources drops citations with no web URL and falls back to the URL for a missing title", () => {
  assert.deepEqual(citedSources([
    { type: "char_location", document_title: "fetched page" },
    { url: "javascript:alert(1)", title: "x" },
    { url: "https://a.example/", title: "  " },
    null,
  ]), [{ url: "https://a.example/", title: "https://a.example/" }]);
  assert.deepEqual(citedSources(undefined), []);
});

test("sourcesMarkdown lists only the cited pages the text does not link, under the heading", () => {
  const text = "Per https://a.example. and (https://b.example/news/#top), see <https://c.example/x?utm_source=openai>";
  const sources = [
    { url: "https://a.example/?utm_source=openai", title: "A" },
    { url: "https://b.example/news", title: "B" },
    { url: "https://c.example/x", title: "C" },
    { url: "https://d.example/", title: "D" },
  ];
  assert.equal(sourcesMarkdown(text, sources, "Additional sources"), "### Additional sources\n\n- [D](<https://d.example/>)");
  assert.equal(sourcesMarkdown(text, sources.slice(0, 3), "Additional sources"), "");
  assert.equal(sourcesMarkdown("plan", [], "x"), "");
  assert.equal(sourcesMarkdown("plan", undefined, "x"), "");
});

test("sourcesMarkdown finds URLs with brackets, non-ASCII paths or bold around them in the text", () => {
  const text = [
    "1. John — https://en.wikipedia.org/wiki/John_Smith_(politician)",
    "[Jane](https://en.wikipedia.org/wiki/Jane_Doe_(actor))",
    "2. サイバー — https://ja.wikipedia.org/wiki/サイバーエージェント、ほか",
    "**https://a.example/x**",
  ].join("\n");
  const sources = [
    { url: "https://en.wikipedia.org/wiki/John_Smith_(politician)", title: "John" },
    { url: "https://en.wikipedia.org/wiki/Jane_Doe_(actor)", title: "Jane" },
    { url: "https://ja.wikipedia.org/wiki/%E3%82%B5%E3%82%A4%E3%83%90%E3%83%BC%E3%82%A8%E3%83%BC%E3%82%B8%E3%82%A7%E3%83%B3%E3%83%88", title: "CA" },
    { url: "https://a.example/x", title: "X" },
  ];
  assert.equal(sourcesMarkdown(text, sources, "H"), "");
  assert.equal(sourcesMarkdown("(see https://en.wikipedia.org/wiki/John)", [{ url: "https://en.wikipedia.org/wiki/John", title: "J" }], "H"), "");
});

test("sourcesMarkdown keeps each page on one line and its link intact whatever the title and URL hold", () => {
  const md = sourcesMarkdown("", [{ url: "https://a.example/a b>c\\", title: "  Profile ](x)\n\n# [not a heading] *_`<b>  " }], "H");
  assert.equal(md, "### H\n\n- [Profile \\](x) # \\[not a heading\\] \\*\\_\\`\\<b\\>](<https://a.example/a%20b%3Ec%5C>)");
});
