// meeting-coach Web の通し E2E  3社の AI の API は page.route で横取りしてモックを返す
// ja は Gemini、en は OpenAI で通し、Claude のセッションで設定画面 (AI の切り替え・キーの保存・全消去) を見る
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";
import { start } from "./server.mjs";
import { respond } from "./mock.mjs";

const HERE = path.dirname(new URL(import.meta.url).pathname);
const REPO = process.env.REPO || "/repo";
const BASE = "http://127.0.0.1:8010/web/";
const SHOTS = path.join(HERE, "shots");
const KEYS = {
  anthropic: "sk-ant-e2e-dummy-not-a-real-key",
  openai: "sk-e2e-openai-dummy-not-a-real-key",
  gemini: "AIza-e2e-gemini-dummy-not-a-real-key",
};
const HOSTS = {
  anthropic: "https://api.anthropic.com/**",
  openai: "https://api.openai.com/**",
  gemini: "https://generativelanguage.googleapis.com/**",
};
// 各社の認証ヘッダから、送られたキーを取り出す
const SENT_KEY = {
  anthropic: (h) => h["x-api-key"],
  openai: (h) => (h.authorization || "").replace(/^Bearer /, ""),
  gemini: (h) => h["x-goog-api-key"],
};
const BOOT_MS = 240_000;
const RUN_MS = 180_000;
fs.mkdirSync(SHOTS, { recursive: true });

const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`); };
const ex = (f) => fs.readFileSync(path.join(REPO, "examples", f), "utf8");

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "POST, OPTIONS",
  "access-control-allow-headers": "*",
  "access-control-expose-headers": "*",
};

/** @param ai 設定で選ぶ AI  ほかの会社に飛んだ呼び出しは s.wrongAI に数える */
async function newSession(browser, lang, ai) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: lang === "ja" ? "ja-JP" : "en-US" });
  const s = { ctx, ai, calls: [], errors: [], csp: [], badKey: 0, wrongAI: 0, labelled: "" };
  for (const [provider, host] of Object.entries(HOSTS)) {
    await ctx.route(host, async (route) => {
      const req = route.request();
      if (req.method() === "OPTIONS") {
        await route.fulfill({ status: 204, headers: { ...CORS, "access-control-allow-headers": req.headers()["access-control-request-headers"] || "*" } });
        return;
      }
      const h = req.headers();
      if (SENT_KEY[provider](h) !== KEYS[provider]) s.badKey++;
      if (provider !== s.ai) s.wrongAI++;
      const body = JSON.parse(req.postData() || "{}");
      const { kind, message } = respond(provider, body, { labelled: s.labelled });
      s.calls.push({ provider, kind, url: req.url(), model: body.model, store: body.store, tools: body.tools, urlsOnly: /cannot search the web/.test(req.postData() || "") });
      await route.fulfill({ status: 200, headers: { ...CORS, "content-type": "application/json", "request-id": "req_mock" }, body: JSON.stringify(message) });
    });
  }
  // 外へ出る通信は CDN と API のモック以外に無いことを見る
  await ctx.addInitScript(() => {
    window.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
  });
  const page = await ctx.newPage();
  page.on("console", (m) => {
    if (m.type() === "error") s.errors.push(m.text());
    if (/Content Security Policy/i.test(m.text())) s.csp.push(m.text());
  });
  page.on("pageerror", (e) => s.errors.push(`pageerror: ${e.message}`));
  page.on("requestfailed", (r) => { if (!/favicon/.test(r.url())) s.errors.push(`requestfailed: ${r.url()} ${r.failure()?.errorText}`); });
  s.page = page;
  return s;
}

async function waitBoot(page) {
  await page.waitForFunction(() => !document.querySelector("#load-form button").disabled || document.querySelector("#status.error"), null, { timeout: BOOT_MS });
  const err = await page.locator("#status.error").count();
  if (err) throw new Error(`boot failed: ${await page.locator("#status").textContent()}`);
}

async function openApp(s) {
  await s.page.goto(BASE, { waitUntil: "domcontentloaded" });
  await waitBoot(s.page);
}

const F = "#settings-form";

/** 設定で AI を選んでダミーキーを入れて保存する  model を渡すと「その他」で手入力する */
async function saveSettings(s, lang, ai, { remember = false, model } = {}) {
  const p = s.page;
  await p.click('.tabs button[data-tab="settings"]');
  await p.selectOption(`${F} select[name="provider"]`, ai);
  await p.fill(`${F} input[name="key"]`, KEYS[ai]);
  await p.setChecked(`${F} input[name="remember"]`, remember);
  if (model) {
    await p.selectOption(`${F} select[name="model"]`, "__other");
    await p.fill(`${F} input[name="model_custom"]`, model);
  }
  await p.selectOption(`${F} select[name="lang"]`, lang);
  await p.click(`${F} button[type=submit]`);
  await p.waitForFunction((l) => document.documentElement.lang === l, lang);
  s.ai = ai;
}

/** 設定フォームにいま出ている AI まわりの中身 */
function formView(p) {
  return p.evaluate(() => {
    const f = document.querySelector("#settings-form").elements;
    const notes = document.querySelector("#s-notes");
    return {
      ai: f.provider.value, label: document.querySelector("#s-key-label").textContent, key: f.key.value,
      placeholder: f.key.placeholder, link: document.querySelector("#key-link").href, remember: f.remember.checked,
      model: f.model.value, custom: f.model_custom.value, customShown: !f.model_custom.closest("label").hidden,
      warn: notes.hidden ? 0 : notes.querySelectorAll(".ai-note.warn").length, notes: notes.hidden ? "" : notes.textContent,
    };
  });
}

/** 全タブの上に出る注意  {shown, warn, text} */
function bannerView(p) {
  return p.evaluate(() => {
    const b = document.querySelector("#ai-banner");
    return { shown: !b.hidden && b.offsetParent !== null, warn: b.querySelectorAll(".ai-note.warn").length, text: b.textContent };
  });
}

const storedKeys = (p) => p.evaluate(() => {
  const pick = (s) => Object.keys(s).filter((k) => k.startsWith("mc.")).sort();
  return { local: pick(localStorage), session: pick(sessionStorage) };
});

async function waitDone(p) {
  await p.waitForFunction(() => {
    const st = document.querySelector("#status");
    return st.classList.contains("error") || /使ったトークン|Tokens used/.test(st.textContent);
  }, null, { timeout: RUN_MS });
  const st = p.locator("#status");
  if (await st.evaluate((e) => e.classList.contains("error"))) throw new Error(`app error: ${await st.textContent()}`);
}

async function review(s, label, { paste, file, assignNames, intake }) {
  const p = s.page;
  const before = s.calls.length;
  await p.click('.tabs button[data-tab="review"]');
  if (paste) await p.fill('#load-form textarea[name="paste"]', paste);
  if (file) await p.setInputFiles('#load-form input[name="file"]', file);
  await p.click("#load-form button[type=submit]");
  await p.waitForFunction(() => !document.querySelector("#assign-form").hidden || !document.querySelector("#intake-form").hidden || document.querySelector("#status.error"), null, { timeout: RUN_MS });
  const assignShown = await p.locator("#assign-form").isVisible();
  if (assignNames) {
    check(`${label}: 話者なしの入力で割り当てフォームが出る`, assignShown);
    await p.fill('#assign-form input[name="names"]', assignNames);
    await p.click("#assign-form button[type=submit]");
    await p.waitForFunction(() => !document.querySelector("#intake-form").hidden || document.querySelector("#status.error"), null, { timeout: RUN_MS });
    const info = await p.locator("#load-info").textContent();
    check(`${label}: 割り当て後に話者が入る`, assignNames.split(",").every((n) => info.includes(n.trim())), info);
  }
  await p.locator("#intake-form").waitFor({ state: "visible" });
  const f = "#intake-form";
  for (const [name, value] of Object.entries(intake.select || {})) await p.selectOption(`${f} select[name="${name}"]`, value);
  for (const [name, value] of Object.entries(intake.fill || {})) await p.fill(`${f} input[name="${name}"]`, value);
  await p.evaluate(() => { document.querySelector("#status").textContent = ""; });
  await p.click(`${f} button[type=submit]`);
  await waitDone(p);

  const out = p.locator("#review-out");
  const nums = await out.locator(".tracks .track-score .num").allTextContents();
  check(`${label}: .tracks に会議点・自分点の数字`, nums.length === 2 && nums.every((n) => /^\d+$/.test(n.trim())), `scores=${nums.join("/")}`);
  const acts = await out.locator(".next-actions li").count();
  check(`${label}: .next-actions に項目`, acts > 0, `${acts} 件`);
  const cards = await out.locator(".comments .note-card").count();
  const marks = await out.locator(".comments mark").count();
  const missingText = intake.lang === "ja" ? "本文で見つからなかった引用" : "Quote not located in the line";
  const missing = await out.locator(".comments .note-absence", { hasText: missingText }).count();
  check(`${label}: .comments にカードと mark`, cards > 0 && marks > 0 && missing === 0, `cards=${cards} marks=${marks} 引用見失い=${missing}`);
  const rep = out.locator("details.full-report");
  const hasRep = await rep.count();
  if (hasRep) await rep.locator("summary").click();
  const repText = hasRep ? await rep.locator(".report-body").innerText() : "";
  check(`${label}: details.full-report`, hasRep === 1 && /モック|mock/.test(repText), `${repText.length} 文字`);
  const mine = s.calls.slice(before).map((c) => c.kind);
  const judges = mine.filter((k) => k === "judge").length;
  check(`${label}: API 呼び出しの形 (判定のやり直し 0 回)`, judges === 1 && mine.includes("report") && !mine.includes("unknown"), mine.join(" → "));
}

async function shots(s, name) {
  const p = s.page;
  await p.setViewportSize({ width: 1280, height: 900 });
  const wide = path.join(SHOTS, `${name}-1280.png`);
  await p.screenshot({ path: wide, fullPage: true });
  await p.setViewportSize({ width: 390, height: 844 });
  await p.waitForTimeout(200);
  const overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  const culprits = overflow > 0 ? await p.evaluate(() => [...document.querySelectorAll("body *")]
    .filter((e) => e.offsetParent && e.getBoundingClientRect().right > window.innerWidth + 1)
    .filter((e) => ![...e.children].some((c) => c.getBoundingClientRect().right > window.innerWidth + 1))
    .slice(0, 4).map((e) => `${e.tagName.toLowerCase()}${e.className ? "." + e.className : ""}[${Math.round(e.getBoundingClientRect().right)}px] "${e.textContent.trim().slice(0, 40)}"`)) : [];
  const narrow = path.join(SHOTS, `${name}-390.png`);
  await p.screenshot({ path: narrow, fullPage: true });
  await p.setViewportSize({ width: 1280, height: 900 });
  check(`${name}: 幅390で横スクロールなし`, overflow <= 0, `はみ出し ${overflow}px ${culprits.join(" ; ")}`);
  return [wide, narrow];
}

async function historyRows(p, expect) {
  // 前回の描画が残っていることがあるので、期待の行数になるまで最大15秒待ってから数える
  await p.evaluate(() => document.querySelector("#score-table").replaceChildren());
  await p.click('.tabs button[data-tab="history"]');
  await p.waitForFunction(() => document.querySelector("#score-table").textContent.trim().length > 0, null, { timeout: 30_000 });
  await p.waitForFunction((n) => document.querySelectorAll("#score-table table.scores tr").length - 1 >= n, expect, { timeout: 15_000 }).catch(() => {});
  return p.locator("#score-table table.scores tr").count().then((n) => Math.max(0, n - 1));
}

async function prepare(s, label, fields) {
  const p = s.page;
  const before = s.calls.length;
  await p.click('.tabs button[data-tab="prepare"]');
  for (const [name, value] of Object.entries(fields)) await p.fill(`#prep-form [name="${name}"]`, value);
  await p.evaluate(() => { document.querySelector("#status").textContent = ""; });
  await p.click("#prep-form button[type=submit]");
  await waitDone(p);
  const outText = await p.locator("#prep-out").innerText();
  const status = await p.locator("#status").textContent();
  const kinds = s.calls.slice(before).map((c) => c.kind);
  check(`${label}: 準備が通り計画が保存される`, /モック|mock/.test(outText) && /P-\d{8}-\d+/.test(status) && kinds.join(",") === "prep_plan,prep_extract", `${kinds.join(" → ")} / ${status.trim().slice(0, 60)}`);
}

async function finish(s, label) {
  const csp = [...s.csp, ...(await s.page.evaluate(() => window.__csp))];
  check(`${label}: コンソールエラー 0 件`, s.errors.length === 0, s.errors.slice(0, 5).join(" | "));
  check(`${label}: CSP 違反 0 件`, csp.length === 0, csp.slice(0, 5).join(" | "));
  check(`${label}: API には入力したダミーキーだけが送られる`, s.badKey === 0 && s.calls.length > 0, `calls=${s.calls.length}`);
  check(`${label}: 選んだ AI の会社にだけ送られる`, s.wrongAI === 0, `ほかの会社へ ${s.wrongAI} 件`);
  await s.ctx.close();
}

async function step(label, fn) {
  try { await fn(); } catch (e) { check(`${label}: 例外なく完走`, false, String(e.message).split("\n")[0]); }
}

// ---------------------------------------------------------------- 実行
const server = await start(REPO, 8010);
const browser = await chromium.launch();
const shotList = [];

// ---- ja: Gemini で通し
{
  const s = await newSession(browser, "ja", "gemini");
  await step("ja", async () => {
    await openApp(s);
    await saveSettings(s, "ja", "gemini");
    await s.page.click('.tabs button[data-tab="review"]');
    const b = await bannerView(s.page);
    check("ja: Gemini を選ぶと採点のタブにも無料枠の警告・準備は検索しない注意・試験的の印が出る", b.shown && b.warn === 1 && /無料枠/.test(b.text) && /Web を検索しません/.test(b.text) && /試験的/.test(b.text) && !/動作未確認/.test(b.text), b.text.slice(0, 80));
    await review(s, "ja 商談 (話者あり)", {
      paste: ex("ja-external-meet.txt"),
      intake: { lang: "ja", select: { meeting_type: "external", me: "佐藤", facilitator: "me", "rel:田中": "external" }, fill: { scheduled: "30" } },
    });
    shotList.push(...await shots(s, "ja-review-external"));
    const n1 = await historyRows(s.page, 1);
    check("ja: 履歴に1行増える", n1 === 1, `${n1} 行`);
    await s.page.reload({ waitUntil: "domcontentloaded" });
    await waitBoot(s.page);
    const n2 = await historyRows(s.page, 1);
    check("ja: リロード後も履歴が残る (IndexedDB)", n2 === 1, `${n2} 行`);
    shotList.push(...await shots(s, "ja-history"));

    s.labelled = ex("ja-1on1-plain.txt");
    const plain = s.labelled.replace(/^(\[[\d:]+\]) [^:\s]+: /gm, "$1 ");
    await review(s, "ja 1on1 (話者なし→割り当て)", {
      paste: plain, assignNames: "佐藤, 山本",
      intake: { lang: "ja", select: { meeting_type: "one-on-one", my_position: "report", me: "佐藤", facilitator: "山本", "rel:山本": "manager" }, fill: { date: "2026-10-02", scheduled: "30" } },
    });
    shotList.push(...await shots(s, "ja-review-assigned"));
    const n3 = await historyRows(s.page, 2);
    check("ja: 2件目で履歴が2行になる", n3 === 2, `${n3} 行`);

    await prepare(s, "ja", { name: "山本 太郎", org: "サンプル商事", goal: "予算の判断をもらう" });
    shotList.push(...await shots(s, "ja-prepare"));
    const urls = s.calls.map((c) => new URL(c.url).pathname);
    check("ja: Gemini には既定のモデルで送られる", urls.length > 0 && urls.every((u) => u.endsWith("/models/gemini-flash-latest:generateContent")), [...new Set(urls)].join(" "));
    const tools = s.calls.filter((c) => c.kind === "prep_plan").map((c) => JSON.stringify(c.tools));
    const told = s.calls.filter((c) => c.kind === "prep_plan").every((c) => c.urlsOnly);
    check("ja: Gemini の準備は Google 検索を使わず URL を読むだけ", tools.length === 1 && tools[0] === '[{"urlContext":{}}]' && told, `${tools.join(" ")} 指示=${told}`);
  });
  await finish(s, "ja");
}

// ---- en: OpenAI で通し
{
  const s = await newSession(browser, "en", "openai");
  await step("en", async () => {
    await openApp(s);
    await saveSettings(s, "en", "openai");
    await s.page.click('.tabs button[data-tab="review"]');
    const b = await bannerView(s.page);
    check("en: OpenAI では警告なしで未確認の印だけが出る", b.shown && b.warn === 0 && /OpenAI has not been tested/.test(b.text), b.text.slice(0, 80));
    await review(s, "en team meeting (VTT upload)", {
      file: path.join(REPO, "examples/en-team-meeting.vtt"),
      intake: { lang: "en", select: { meeting_type: "meeting", me: "Alex", facilitator: "me", "rel:Jordan": "peer", "rel:Sam": "peer" }, fill: { date: "2026-10-03", scheduled: "30" } },
    });
    shotList.push(...await shots(s, "en-review-meeting"));
    const n1 = await historyRows(s.page, 1);
    check("en: 履歴に1行増える", n1 === 1, `${n1} 行`);
    await s.page.reload({ waitUntil: "domcontentloaded" });
    await waitBoot(s.page);
    const n2 = await historyRows(s.page, 1);
    check("en: リロード後も履歴が残る (IndexedDB)", n2 === 1, `${n2} 行`);
    shotList.push(...await shots(s, "en-history"));
    await prepare(s, "en", { name: "Jordan Lee", org: "Example Corp", goal: "Agree the vendor shortlist" });
    shotList.push(...await shots(s, "en-prepare"));
    check("en: OpenAI には既定のモデルで store:false を付けて送られる", s.calls.length > 0 && s.calls.every((c) => c.model === "gpt-6-astra" && c.store === false),
      [...new Set(s.calls.map((c) => `${c.model}/${c.store}`))].join(" "));
    const prep = s.calls.filter((c) => c.kind === "prep_plan");
    check("en: OpenAI の準備は Web 検索を使う", prep.length === 1 && prep[0].tools?.some((t) => t.type === "web_search") && !prep[0].urlsOnly, JSON.stringify(prep[0]?.tools));
  });
  await finish(s, "en");
}

// ---- 設定画面: AI の切り替え・キーの保存・モデルの手入力・全消去  採点は Claude で通す
{
  const s = await newSession(browser, "ja", "anthropic");
  s.page.on("dialog", (d) => d.accept());
  await step("設定", async () => {
    const p = s.page;
    await openApp(s);
    await p.click('.tabs button[data-tab="settings"]');
    check("設定: 設定のタブでは上の注意を重ねて出さない", !(await bannerView(p)).shown);
    let v = await formView(p);
    check("設定: 既定は Claude で、未確認の印だけが出る", v.ai === "anthropic" && v.label.includes("Claude") && v.placeholder === "sk-ant-..." && v.warn === 0 && /Claude は、実際の API/.test(v.notes), JSON.stringify(v));

    await p.selectOption(`${F} select[name="provider"]`, "gemini");
    v = await formView(p);
    check("設定: Gemini に切り替えるとキー欄・取得先・無料枠の警告・準備は検索しない注意・試験的の印が変わる",
      v.label.includes("Gemini") && v.placeholder === "AIza..." && v.key === "" && v.link.startsWith("https://aistudio.google.com/") && v.warn === 1 && /無料枠/.test(v.notes) && /Web を検索しません/.test(v.notes) && /試験的/.test(v.notes),
      `${v.label} / ${v.placeholder} / ${v.link} / warn=${v.warn}`);
    await saveSettings(s, "ja", "gemini", { remember: true });

    await p.selectOption(`${F} select[name="provider"]`, "openai");
    v = await formView(p);
    check("設定: OpenAI に切り替えるとキー欄は空で、無料枠の警告が消える",
      v.label.includes("OpenAI") && v.placeholder === "sk-..." && v.key === "" && !v.remember && v.link.startsWith("https://platform.openai.com/") && v.warn === 0 && /OpenAI は、実際の API/.test(v.notes),
      `${v.label} / ${v.placeholder} / key=${v.key.length} / warn=${v.warn}`);
    await p.selectOption(`${F} select[name="model"]`, "__other");
    check("設定: 「その他」を選ぶとモデル名の欄が出る", (await formView(p)).customShown);
    await saveSettings(s, "ja", "openai", { model: "gpt-e2e-typed-model" });

    await p.selectOption(`${F} select[name="provider"]`, "gemini");
    v = await formView(p);
    check("設定: Gemini に戻すと保存したキーが戻る", v.key === KEYS.gemini && v.remember, `key=${v.key === KEYS.gemini} remember=${v.remember}`);

    await p.reload({ waitUntil: "domcontentloaded" });
    await waitBoot(p);
    const b = await bannerView(p);
    check("設定: リロード後は OpenAI の印に替わり、Gemini の警告は消える", b.shown && b.warn === 0 && /OpenAI/.test(b.text), b.text.slice(0, 80));
    await p.click('.tabs button[data-tab="settings"]');
    v = await formView(p);
    check("設定: リロード後も OpenAI と手入力のモデル名が残る", v.ai === "openai" && v.key === KEYS.openai && v.model === "__other" && v.custom === "gpt-e2e-typed-model" && v.customShown, JSON.stringify({ ai: v.ai, model: v.model, custom: v.custom }));
    const st = await storedKeys(p);
    const keysIn = (list) => list.filter((k) => k.startsWith("mc.key.")).join(",");
    check("設定: キーは AI ごとに分けて保存され、「このブラウザに保存」は Gemini だけ",
      keysIn(st.local) === "mc.key.gemini" && keysIn(st.session) === "mc.key.gemini,mc.key.openai", `local=${keysIn(st.local)} session=${keysIn(st.session)}`);

    const before = s.calls.length;
    await prepare(s, "設定 OpenAI", { name: "山本 太郎", org: "サンプル商事", goal: "予算の判断をもらう" });
    const typed = s.calls.slice(before);
    check("設定: 手入力のモデル名で送られる", typed.length > 0 && typed.every((c) => c.provider === "openai" && c.model === "gpt-e2e-typed-model"), typed.map((c) => c.model).join(" "));

    await saveSettings(s, "ja", "anthropic");
    await review(s, "ja 商談 (Claude)", {
      paste: ex("ja-external-meet.txt"),
      intake: { lang: "ja", select: { meeting_type: "external", me: "佐藤", facilitator: "me", "rel:田中": "external" }, fill: { scheduled: "30" } },
    });
    shotList.push(...await shots(s, "ja-review-claude"));
    await p.click('.tabs button[data-tab="settings"]');
    shotList.push(...await shots(s, "ja-settings"));

    await p.click('.tabs button[data-tab="history"]');
    await p.evaluate(() => { document.querySelector("#status").textContent = ""; });
    await p.click("#wipe");
    await p.waitForFunction(() => /消しました/.test(document.querySelector("#status").textContent), null, { timeout: 30_000 });
    const gone = await storedKeys(p);
    await p.click('.tabs button[data-tab="settings"]');
    v = await formView(p);
    check("設定: 全消去で3社ぶんのキーと設定が消え、既定に戻る",
      gone.local.length === 0 && gone.session.length === 0 && v.ai === "anthropic" && v.key === "",
      `local=${gone.local.join(",")} session=${gone.session.join(",")} ai=${v.ai}`);
  });
  await finish(s, "設定");
}

await browser.close();
server.close();
fs.writeFileSync(path.join(HERE, "results.json"), JSON.stringify({ results, shots: shotList }, null, 1));
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} PASS`);
process.exit(failed.length ? 1 : 0);
