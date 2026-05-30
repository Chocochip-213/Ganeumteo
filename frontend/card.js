// 9요소 진단 카드 — 데이터주도(과적합 0). 백엔드 ReturnEnvelope(_return) 그대로 렌더.
// card 이중형태: 성공(영문키, legal_reasoning 존재 또는 terminal=completed) vs 보류(한글키). 양쪽 방어적 읽기.
import { classifyVerdict, TONE_KO, statusKo } from "./verdict.js";

function el(t, c, x) { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
function sect(title, empty) { const s = el("div", "sect" + (empty ? " empty" : "")); s.appendChild(el("h3", null, title)); return s; }
function arr(v) { return Array.isArray(v) ? v : []; }
function intCount(v) { return typeof v === "number" ? v : arr(v).length; }   // card.citations는 int, state는 list

export function renderCard(root, env, stateCits) {
  root.innerHTML = "";
  if (!env || !env.card) { root.appendChild(el("p", "placeholder", "결과가 없습니다.")); return; }
  const card = env.card;
  const success = !!card.legal_reasoning || env.terminal_reason === "completed";
  root.appendChild(verdictBadge(card.verdict, env));
  if (success) renderSuccess(root, card, arr(stateCits));
  else renderAbstain(root, card, env);
  root.appendChild(footer(env, card));
}

function verdictBadge(v, env) {
  const c = classifyVerdict(v);
  const wrap = el("div");
  const b = el("div", "verdict-badge tone-" + c.tone);
  b.appendChild(el("span", null, c.label));               // '위험·금지' 가운뎃점 보존, 한 칩
  const st = el("span", "st"); const sp = el("span", null, statusKo(env.terminal_reason)); st.appendChild(sp);
  b.appendChild(st); wrap.appendChild(b);
  wrap.appendChild(el("div", "status-line",
    `${TONE_KO[c.tone] || c.label}  ·  종료=${env.terminal_reason || "?"}  ·  ${statusKo(env.terminal_reason)}`));
  return wrap;
}

// ── 성공 카드(영문키 9요소) ──
function renderSuccess(root, card, cits) {
  // 1. 법적 논증 체인
  const lr = card.legal_reasoning || {};
  const steps = arr(lr.steps);
  const s1 = sect("법적 판단 근거 (논증 체인)", steps.length === 0);
  if (steps.length === 0) s1.appendChild(el("p", "empty-note", "논증 단계가 생성되지 않았습니다."));
  steps.forEach((st) => {                                  // 0..N 제너릭, kind 가변
    const row = el("div", "step" + (st.status === "확인필요" ? " unresolved" : ""));
    row.appendChild(el("div", "pin", "#" + (st.seq ?? "")));
    const body = el("div");
    const head = el("div");
    head.appendChild(el("span", "kind", st.kind || "단계"));
    head.appendChild(el("span", "fact", st.fact || ""));
    body.appendChild(head);
    if (st.infer) body.appendChild(el("div", null, st.infer));
    // basis tri-state: null(확인필요)=빨강 / vworld=입지출처(법근거 아님) / law·ordin·data=법적근거
    const bcls = !st.basis ? "none" : (st.basis === "vworld" ? "site" : "law");
    const btxt = !st.basis ? "⚠ 근거 미확보 → 확인필요"
      : (st.basis === "vworld" ? "입지 출처(법적 근거 아님)" : "법적 근거: " + st.basis);
    body.appendChild(el("div", "basis " + bcls, btxt));
    row.appendChild(body); s1.appendChild(row);
  });
  root.appendChild(s1);

  // 2. 인허가 의제 (0/1/N)
  const uijae = arr(card.uijae);
  const s2 = sect("인허가 의제 (함께 처리되는 인허가)", uijae.length === 0);
  if (uijae.length === 0) s2.appendChild(el("p", "empty-note", "의제 해당 없음 (별도 전용허가 등 불요)."));
  else {
    const chips = el("div", "chips");
    uijae.forEach((u) => {
      const chip = el("div", "chip");
      chip.appendChild(el("span", null, `${u.trigger || ""} → ${u.permit_name || ""}`));
      if (u.citation) chip.appendChild(el("span", "badge", "근거"));   // citation 없으면 배지 없음(허용)
      chips.appendChild(chip);
    });
    s2.appendChild(chips);
  }
  root.appendChild(s2);

  // 3. 제출 서류 로드맵 ({stage,count,status} — items[] 없음. 확인필요≠서류 없음)
  const docs = arr(card.documents);
  const s3 = sect("단계별 제출 서류", docs.length === 0);
  if (docs.length === 0) s3.appendChild(el("p", "empty-note", "서류 단계가 산출되지 않았습니다."));
  docs.forEach((d) => {
    const row = el("div", "doc");
    row.appendChild(el("span", null, d.stage || d.stage_key || "단계"));
    const right = el("span");
    if (d.status === "전수확보") right.appendChild(el("span", "cnt ok", `${d.count ?? 0}개 서류 전수확보`));
    else right.appendChild(el("span", "cnt need", "자동확인 실패 → 확인필요"));   // 확인필요 ≠ 서류 0
    row.appendChild(right); s3.appendChild(row);
  });
  root.appendChild(s3);

  // 4. 규제효과 (partial by design — Y건 근거확보)
  const regs = arr(card.reg_effects);
  const s4 = sect("규제별 근거 법령", regs.length === 0);
  if (regs.length === 0) s4.appendChild(el("p", "empty-note", "근거 확보된 규제효과 없음 (중첩 규제는 위 논증/입지 참조)."));
  else {
    s4.appendChild(el("p", "empty-note", `근거 확보 ${regs.length}건 (나머지 규제는 확인필요).`));
    const chips = el("div", "chips");
    regs.forEach((r) => chips.appendChild(el("div", "chip", `${r.reg_name || ""} · ${r.law_name || ""} ${r.article || ""}`)));
    s4.appendChild(chips);
  }
  root.appendChild(s4);

  // 5. 규모 상한 + 6. 작성주체
  const sl = card.scale_limits, au = card.author;
  const s5 = sect("규모 상한 · 작성 주체");
  const kv = el("dl", "kv");
  if (sl && typeof sl === "object") {
    const both = !sl.energy_saving_required && !sl.structural_safety_required;
    kv.appendChild(el("dt", null, "에너지절약계획서"));
    kv.appendChild(el("dd", null, sl.energy_saving_required ? "필요 (연면적 ≥500㎡)" : "불요"));
    kv.appendChild(el("dt", null, "구조안전확인서"));
    kv.appendChild(el("dd", null, sl.structural_safety_required ? "필요 (연면적 ≥200㎡ 또는 2층↑)" : "불요"));
    if (both) { kv.appendChild(el("dt", null, "규모 임계")); kv.appendChild(el("dd", null, "해당 임계 없음")); }
  } else { kv.appendChild(el("dt", null, "규모 상한")); kv.appendChild(el("dd", null, "미산출")); }
  kv.appendChild(el("dt", null, "작성 주체"));
  if (au && typeof au === "object")
    kv.appendChild(el("dd", null, au.requires_architect ? "건축사 필수 (건축법 §23①)" : "건축사 불요 (§23① 단서)"));
  else kv.appendChild(el("dd", null, "미확인"));   // false(불요)와 missing(미확인) 구분
  s5.appendChild(kv); root.appendChild(s5);

  // 7. 로드맵(합성: 의제+서류 순서) — 프로토 카드키 없음
  const rm = synthRoadmap(uijae, docs);
  if (rm.length) {
    const s7 = sect("진행 로드맵");
    const chips = el("div", "chips");
    rm.forEach((s, i) => chips.appendChild(el("div", "chip", `${i + 1}. ${s}`)));
    s7.appendChild(chips); root.appendChild(s7);
  }

  // 8. 함정/주의(합성: scale불린 + abstentions + 확인필요 step/doc) — 프로토 카드키 없음
  const pit = synthPitfalls(card);
  if (pit.length) {
    const s8 = sect("주의 · 함정");
    pit.forEach((p) => s8.appendChild(el("div", "pitfall", p)));
    root.appendChild(s8);
  }

  // 9. 근거(citation) — card.citations는 int, 실제 객체는 state.citations. vworld는 '입지 출처'(법근거 미계수)
  const subst = cits.filter((c) => ["law", "ordin", "data"].includes(c.source));
  const s9 = sect(`인용 근거 (법적 ${subst.length}건)`, cits.length === 0);
  if (cits.length === 0) s9.appendChild(el("p", "empty-note", "인용 근거 없음."));
  cits.forEach((c) => s9.appendChild(citeRow(c)));
  root.appendChild(s9);

  // 부담금: 단가 API 없음 → 금액 절대 안 씀
  const sl2 = sect("부담금");
  sl2.appendChild(el("p", "empty-note", "단가 미제공 → 확인필요 (금액은 측량·설계 후 산정)."));
  root.appendChild(sl2);
}

function citeRow(c) {
  const row = el("div", "cite");
  const head = el("div");
  head.appendChild(el("span", "src " + (c.source || ""), c.source || "?"));
  head.appendChild(el("span", null, [c.law_name, c.article, c.title].filter(Boolean).join(" ")));
  if (c.extract_method) head.appendChild(el("span", "badge", " · " + c.extract_method));
  row.appendChild(head);
  if (c.quote) row.appendChild(el("span", "quote", c.quote));
  if (c.url) { const a = el("a", null, "원문 더보기"); a.href = c.url; a.target = "_blank"; row.appendChild(a); }
  return row;
}

// ── 보류 카드(한글키) ──
function renderAbstain(root, card, env) {
  const s = sect("자동 판정 보류");
  const why = card["사유"];
  s.appendChild(el("p", "empty-note",
    "근거가 충분치 않아 자동 판정을 보류했습니다. " + (statusKo(env.terminal_reason)) + " — 아래 확인이 필요합니다."));
  const ip = card["입지"] || {};
  const kv = el("dl", "kv");
  [["지목", ip["지목"]], ["용도지역", ip["용도지역"]], ["도로접면", ip["도로접면"]]].forEach(([k, v]) => {
    kv.appendChild(el("dt", null, k)); kv.appendChild(el("dd", null, v == null ? "미확보" : String(v)));
  });
  s.appendChild(kv);
  root.appendChild(s);
  // 사유 목록
  const sr = sect("보류 사유");
  if (Array.isArray(why)) why.forEach((w) => sr.appendChild(el("div", "pitfall", (w.node ? `[${w.node}] ` : "") + (w["사유"] || JSON.stringify(w)))));
  else sr.appendChild(el("p", "empty-note", String(why || "근거(citation) 0건")));
  root.appendChild(sr);
}

// ── 합성 ──
function synthRoadmap(uijae, docs) {
  const order = [];
  arr(uijae).forEach((u) => { if (u.permit_name) order.push(u.permit_name); });
  const seen = new Set(order);
  arr(docs).forEach((d) => { const s = d.stage || d.stage_key; if (s && !seen.has(s)) { order.push(s); seen.add(s); } });
  return order;
}
function synthPitfalls(card) {
  const out = [];
  const sl = card.scale_limits;
  if (sl && sl.energy_saving_required) out.push("연면적 500㎡ 이상 — 에너지절약계획서 제출 대상.");
  if (sl && sl.structural_safety_required) out.push("연면적 200㎡ 이상 또는 2층 이상 — 구조안전 확인 대상.");
  arr(card.legal_reasoning?.steps).forEach((s) => {
    if (s.status === "확인필요") out.push(`'${s.kind}' 단계 근거 미확보 → 담당 부서/건축사 확인 필요.`);
  });
  arr(card.documents).forEach((d) => { if (d.status !== "전수확보") out.push(`'${d.stage || d.stage_key}' 단계 서류 자동확인 실패 → 직접 확인 필요.`); });
  arr(card.abstentions).forEach((a) => out.push((a.node ? `[${a.node}] ` : "") + (a["사유"] || "")));
  return out.filter(Boolean);
}

function footer(env, card) {
  const f = el("div", "foot");
  f.textContent = `종료 사유 ${env.terminal_reason || "?"} · 인용 ${intCount(card.citations)}건 · 추정값은 측량·설계 후 확정.`;
  return f;
}
