// 프론트 렌더 검증(브라우저 없이, node). 최소 fake DOM + verdict.js/card.js를 실제 import.
// 실 픽스처 + 합성 stress벡터(전 verdict공간·0/1/N·미지값·결측키·abstain) 전부 크래시0 + 핵심 불변식.
import fs from "fs";
import path from "path";
import { classifyVerdict } from "../frontend/verdict.js";
import { renderCard } from "../frontend/card.js";

// ── 최소 fake DOM ──
function mkEl(tag) {
  const e = {
    tagName: tag, className: "", _text: "", _html: "", children: [], style: {}, dataset: {}, href: "", target: "",
    set textContent(v) { this._text = v == null ? "" : String(v); },
    get textContent() { return this._text; },
    set innerHTML(v) { this._html = v; if (v === "") this.children = []; },
    get innerHTML() { return this._html; },
    appendChild(c) { this.children.push(c); return c; },
    querySelector() { return null; },
  };
  return e;
}
globalThis.document = { createElement: mkEl };
function allText(n) { let t = n._text || ""; for (const c of (n.children || [])) t += " " + allText(c); return t; }
function nodeCount(n) { let k = 1; for (const c of (n.children || [])) k += nodeCount(c); return k; }

let FAIL = 0;
function check(name, cond, extra) { console.log(`  ${cond ? "PASS" : "FAIL"} ${name}${extra ? " — " + extra : ""}`); if (!cond) FAIL++; }

// ── 1. classifyVerdict: 전 verdict 공간 + 미지값/빈값/null ──
console.log("[1] classifyVerdict");
[["가능", "affirmative"], ["가능(조건부)", "conditional"], ["위험·금지", "danger"], ["확인필요", "neutral"],
 ["불가", "danger"], ["완전_미지_값", "neutral"], ["", "neutral"], [null, "neutral"], ["가능 (단 농지전용 선행)", "affirmative"]]
  .forEach(([inp, exp]) => { const r = classifyVerdict(inp); check(`'${inp}' → ${r.tone}`, r.tone === exp, `기대 ${exp}`); });
check("'위험·금지' 가운뎃점 보존", classifyVerdict("위험·금지").label === "위험·금지");
check("미지값 raw 플래그", classifyVerdict("xyz").raw === true);

// ── 2. 실제 픽스처 렌더(크래시0 + verdict 라벨 출력) ──
console.log("[2] 실 픽스처 렌더");
const fixdir = path.resolve(import.meta.dirname, "fixtures");
for (const f of fs.readdirSync(fixdir).filter((x) => x.endsWith(".json"))) {
  const p = JSON.parse(fs.readFileSync(path.join(fixdir, f), "utf-8"));
  const root = mkEl("div");
  let ok = true, err = "";
  try { renderCard(root, p._return, p.citations); } catch (e) { ok = false; err = e.message; }
  const txt = allText(root);
  const v = p._return?.card?.verdict ?? "";
  check(`${f} 렌더`, ok && nodeCount(root) > 3 && (v === "" || txt.includes(v)), ok ? `노드 ${nodeCount(root)}` : err);
}

// ── 3. 합성 stress벡터(전 verdict공간·0/1/N·미지값·결측키·abstain) ──
console.log("[3] 합성 stress(렌더러 견고성 — 날조 아님, 테스트 입력)");
const base = (over) => ({ _return: { terminal_reason: "completed", status: "완료", abstentions: [],
  card: Object.assign({ verdict: "가능", legal_reasoning: { steps: [], verdict: "가능", verdict_basis_seq: [] },
    uijae: [], documents: [], scale_limits: { energy_saving_required: false, structural_safety_required: false, notes: [] },
    author: { requires_architect: false, reason: "" }, reg_effects: [], citations: 0, abstentions: [] }, over) }, citations: [] });
const STRESS = [
  ["verdict 가능", base({ verdict: "가능" })],
  ["verdict 가능(조건부)", base({ verdict: "가능(조건부)" })],
  ["verdict 위험·금지", base({ verdict: "위험·금지" })],
  ["verdict 미지값", base({ verdict: "기상천외판정" })],
  ["verdict null", base({ verdict: null })],
  ["uijae N + citation없음", base({ uijae: [{ trigger: "지목=답", permit_name: "농지전용허가", stage_key: "농지전용", citation: null }, { trigger: "형질변경", permit_name: "개발행위허가", stage_key: "개발행위" }] })],
  ["documents 확인필요", base({ documents: [{ stage: "초지전용", count: 0, status: "확인필요" }, { stage: "건축허가", count: 15, status: "전수확보" }] })],
  ["scale 둘다 true", base({ scale_limits: { energy_saving_required: true, structural_safety_required: true, notes: [] } })],
  ["author missing", base({ author: null })],
  ["citations as list(coerce)", base({ citations: [{ source: "law" }, { source: "vworld" }] })],
  ["legal_reasoning steps 다양 basis", base({ legal_reasoning: { steps: [
    { seq: 1, kind: "입지", fact: "지목=답", basis: "vworld", status: "확정" },
    { seq: 2, kind: "행위제한", fact: "자연녹지 카페", basis: null, status: "확인필요" },
    { seq: 3, kind: "조례호목해소", fact: "별표16", basis: "ordin", status: "확정" }], verdict: "확인필요", verdict_basis_seq: [2, 3] } })],
  ["결측키 전부(빈 카드)", { _return: { terminal_reason: "completed", status: "완료", card: { verdict: "확인필요" }, abstentions: [] }, citations: [] }],
  ["abstain 한글키", { _return: { terminal_reason: "site_geocode_failed", status: "재입력필요",
    card: { verdict: "확인필요", terminal: "site_geocode_failed", "사유": [{ node: "geocode", "사유": "지오코딩 실패" }], "입지": { "지목": null, "용도지역": null, "도로접면": null }, citations: 0 }, abstentions: [] }, citations: [] }],
  ["env null", { _return: null, citations: [] }],
];
for (const [name, env] of STRESS) {
  const root = mkEl("div");
  let ok = true, err = "";
  try { renderCard(root, env._return, env.citations); } catch (e) { ok = false; err = e.message; }
  check(name, ok, ok ? "" : err);
}

console.log(`\n총 실패: ${FAIL}`);
process.exit(FAIL ? 1 : 0);
