// =========================================================
//  가늠터 상담실 — 챗 엔진 (실 백엔드 와이어링)
//  온보딩 → 지도모달(카카오 지오코더) → 주소 확정 → 채팅
//  quickActions → 연면적·층수 입력 → /diagnose/stream(SSE)
//  ChatGPT식: 채팅=질문→접힌 "검토 중"(1줄 subtle)→AI 답변 메시지(판정+요약+'자세히 보기').
//  SSE trace(도구호출·사고·근거)는 채팅 숨김 → c.trace[]에 모아 우측 패널(상세 플로우+전체 분해).
//  → interrupt→/resume → done → /diagnose/result. 모르는 kind/결측키도 크래시 없이(데이터주도).
// =========================================================
import { classifyVerdict, statusKo } from "./verdict.js";
import { DICT } from "./terms.js";   // 토지이용 용어사전(2025) 663용어 — hover

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const el = (t, c, h) => { const e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const arr = (v) => (Array.isArray(v) ? v : []);
const lawURL = (q) => "https://www.law.go.kr/법령/" + encodeURIComponent(q || "");
// 출처 원문 링크: data(행위제한 API)는 law_name이 'API 라벨'이라 깨진 링크 → 실제 법령(article의 법령명)으로. 그 외는 law_name.
const lawHref = (c) => {
  if (!c) return null;
  if (c.url) return c.url;
  if (c.source === "data") {
    const ln = String(c.article || "").split(/별표|제\s*\d/)[0].trim();
    return ln ? lawURL(ln) : null;
  }
  return c.law_name ? lawURL(c.law_name) : null;
};

// ── SVG 아이콘 (디자인 원본 재사용) ──
const I = {
  plus: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
  pin: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>',
  send: '<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4 20-7z"/></svg>',
  search: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
  cross: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><line x1="12" y1="2" x2="12" y2="5"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="2" y1="12" x2="5" y2="12"/><line x1="19" y1="12" x2="22" y2="12"/></svg>',
  x: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
  arrow: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>',
  check: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
  file: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
  down: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
  info: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
  bang: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="8" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
  go: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
  cond: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="7" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
  sparkle: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v3M12 18v3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M3 12h3M18 12h3M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/></svg>',
  ext: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>',
  chev: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>',
  route: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="19" r="3"/><path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15"/><circle cx="18" cy="5" r="3"/></svg>',
  list: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>',
  home: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>',
  swap: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>',
  extend: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18"/><path d="M5 21V8l5-4v17"/><path d="M19 21V12l-9-4"/><line x1="16" y1="3" x2="22" y2="3"/></svg>',
  coffee: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8h1a4 4 0 0 1 0 8h-1"/><path d="M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4z"/><line x1="6" y1="1" x2="6" y2="4"/><line x1="10" y1="1" x2="10" y2="4"/><line x1="14" y1="1" x2="14" y2="4"/></svg>',
  brush: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9.06 11.9l8.07-8.06a2.85 2.85 0 1 1 4.03 4.03l-8.06 8.08"/><path d="M7.07 14.94c-1.66 0-3 1.35-3 3.02 0 1.33-2.5 1.52-2 2.02 1.08 1.1 2.49 2.02 4 2.02 2.2 0 4-1.8 4-4.04a3.01 3.01 0 0 0-3-3.02z"/></svg>',
  help: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
};
const I_law = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18"/><path d="M5 7h14"/><path d="M6 7l-3 6a3 3 0 0 0 6 0z"/><path d="M18 7l-3 6a3 3 0 0 0 6 0z"/><path d="M7 21h10"/></svg>';

// ── 용어 사전 (popover) ──
const HAND = {   // 손번역 핵심어 — 사전 정의보다 친절, 머지 시 우선
  "용도지역": ["용도지역", "땅마다 정해진 “쓰임새 등급”. 주거·상업·공업 등으로 나뉘고, 지을 수 있는 건물 종류와 크기가 달라져요."],
  "지목": ["지목", "땅의 공식 용도 분류(대지·전·답·임야 등). “대(垈)”는 건물을 지을 수 있는 땅이에요."],
  "도로접면": ["도로접면", "필지가 도로에 닿은 면. 도로에 접해야 건축이 가능하고, 폭·접면 길이에 따라 건축선·진입 조건이 달라져요."],
  "건폐율": ["건폐율", "대지 면적 중 건물이 “바닥으로 덮는” 비율."],
  "용적률": ["용적률", "대지 면적 대비 “모든 층 바닥을 합한” 비율. 건물을 얼마나 높이(층수) 올릴 수 있는지를 정해요."],
  "근린생활시설": ["근린생활시설", "동네 주민이 자주 쓰는 생활편의 시설(가게·음식점·학원·의원 등) 분류예요."],
  "용도변경": ["용도변경", "건물을 원래 쓰임새와 다른 용도로 바꾸는 것. 예) 사무실 → 카페는 용도변경이에요."],
  "대수선": ["대수선", "건물의 기둥·보·내력벽 같은 “뼈대”를 크게 고치는 공사. 벽지·바닥만 바꾸는 인테리어는 해당하지 않아요."],
  "의제처리": ["의제처리", "건축 허가 하나로 도로·하수도·농지전용 등 관련 인허가를 “함께 받은 것으로 쳐주는” 제도예요."],
  "에너지절약계획서": ["에너지절약계획서", "일정 규모(연면적 500㎡ 이상 등) 건물에 요구되는, 단열·설비 등 에너지 성능 계획 서류예요."],
  "구조안전확인서": ["구조안전확인서", "건물이 자기 무게·바람·지진을 안전하게 견디는지 확인하는 서류. 연면적 200㎡ 이상이나 2층 이상이면 보통 필요해요."],
  "입지": ["입지", "땅의 위치·필지 정보 — 주소·지목·용도지역·도로 접면 등 ‘어디에 짓는가’의 기본 조건이에요."],
  "행위제한": ["행위제한", "그 용도지역에서 어떤 건물을 지을 수 있고 없는지 법으로 정한 제한. ‘여기에 이 건물 돼?’의 1차 판정이에요."],
  "의제": ["의제", "건축 허가 하나로 농지전용·개발행위 등 관련 인허가를 ‘함께 받은 것으로 쳐주는’ 것. 그만큼 챙길 서류가 늘어요."],
  "호목": ["호목", "법령의 항목 구조. 호(號)는 ‘1. 2. 3.’, 목(目)은 ‘가. 나. 다.’ 단위예요. 예) 건축법 별표1 제13호=운동시설."],
  "조례호목해소": ["조례호목해소", "조례가 ‘건축법 별표1 제○호’를 가리키면, 그 호·목을 직접 찾아가 내 건물 용도가 거기 포함되는지 확정하는 과정이에요."],
  "별표": ["별표", "법령 본문 뒤에 붙는 ‘표’. 건축물 용도 분류(별표1)나 제출 서식 등이 표로 정리돼 있어요."],
  "규모": ["규모", "건물의 크기 — 연면적(바닥면적 합)과 층수. 규모에 따라 필요한 서류·검토가 달라져요."],
  "작성주체": ["작성주체", "설계도서를 누가 작성해야 하는지. 일정 규모(연면적 85㎡ 등)를 넘으면 건축사가 설계해야 해요."],
  "부설주차": ["부설주차", "건물을 지을 때 의무로 함께 설치하는 주차장. 용도·면적에 따라 대수가 정해져요."],
  "부담금": ["부담금", "개발할 때 내는 돈. 농지를 바꾸면 농지보전부담금, 산지면 대체산림조성비 등이 있어요."],
};
const GLOSSARY = Object.assign({}, DICT, HAND);   // 토지이용 용어사전 663 + 손번역(손번역 우선)
const SRC_KO = { vworld: "VWorld", law: "국가법령정보센터", ordin: "국가법령정보센터", data: "국토교통부" };
function srcKo(s) { return "출처 · " + (SRC_KO[s] || s || "근거"); }   // '출처' 라벨 + 실제 소스명(VWorld 등 그대로)
// 경량 마크다운 렌더 — LLM 응답의 **굵게**·`코드`·- 목록·줄바꿈만(esc 먼저=주입 안전). 풀 md 라이브러리 불필요.
function mdLite(s) {
  let h = esc(String(s == null ? "" : s));
  h = h.replace(/\*\*([^*]+?)\*\*/g, "<b>$1</b>");
  h = h.replace(/`([^`]+?)`/g, "<code>$1</code>");
  h = h.replace(/^[ \t]*[-*]\s+/gm, "• ");
  h = h.replace(/\n/g, "<br>");
  return h;
}
// 임베디드 하이라이트용 키(3자+, 긴 것 먼저) — 2글자 법률어는 "인가요" 같은 일상어 내부 오탐이 많아 자동 매칭에서 제외.
// 2글자 핵심어(지목·입지 등)는 maybeTerm/T처럼 의도한 라벨 위치에서만 표시한다.
const _TERMKEYS = Object.keys(GLOSSARY).filter((k) => k.length >= 3).sort((a, b) => b.length - a.length);
function termHtml(key, label) {
  return `<span class="term" data-term="${esc(key)}">${esc(label || key)}<span class="term-q">?</span></span>`;
}
const _HANGUL_SYL = /[가-힣]/;   // 한글 완성형 음절 — 단어경계 판정용(item 18)
function linkifyTerms(plain) {   // 평문 → 용어 span(esc 후 단어시작 첫 등장 래핑). HTML 입력 금지(평문만).
  let html = esc(String(plain == null ? "" : plain));
  for (const k of _TERMKEYS) {
    const ek = esc(k);
    // item 18: 단어경계만 매칭 — 앞 글자가 한글 음절이면 단어 중간(어미/조사 내부 부분문자열)이라 skip. 키당 첫 유효 등장만.
    let from = 0, idx;
    while ((idx = html.indexOf(ek, from)) >= 0) {
      const inSpan = html.lastIndexOf("<span", idx) > html.lastIndexOf("</span>", idx);
      const before = idx > 0 ? html[idx - 1] : "";
      if (!inSpan && !(before && _HANGUL_SYL.test(before))) {
        html = html.slice(0, idx) + termHtml(k, k) + html.slice(idx + ek.length);
        break;
      }
      from = idx + ek.length;
    }
  }
  return html;
}
function T(key, label) { const g = GLOSSARY[key]; return termHtml(key, label || (g ? g[0] : key)); }
// GLOSSARY에 있는 토큰이면 용어 span, 아니면 esc
function maybeTerm(text) { return GLOSSARY[text] ? T(text) : esc(text); }

function stepNeedsReview(s) { return s && s.status === "확인필요"; }
function summarizeNames(xs, n = 4) {
  const names = xs.map((s) => String(s.fact || "").trim()).filter(Boolean);
  if (!names.length) return "";
  const head = names.slice(0, n).join(", ");
  return names.length > n ? `${head} 외 ${names.length - n}개` : head;
}
function compactNeedCount(steps) {
  const pending = steps.filter(stepNeedsReview);
  const regN = pending.some((s) => s.kind === "규제효과") ? 1 : 0;
  return pending.filter((s) => s.kind !== "규제효과").length + regN;
}

// ── 채팅 추천 액션 (의도 → use_type) ──
// 구체적 시설을 평이한 말로 — 건축법 분류는 에이전트가 해석(사용자가 제1종/제2종 같은 걸 알 필요 없음)
const ACTIONS = [
  { t: "카페·음식점", d: "휴게/일반음식점", use: "카페", ic: "coffee" },
  { t: "소매점·상가", d: "편의점·옷가게 등", use: "소매점", ic: "home" },
  { t: "사무실", d: "업무시설", use: "사무실", ic: "home" },
  { t: "단독주택", d: "내 집 짓기", use: "단독주택", ic: "home" },
  { t: "다세대·다가구주택", d: "여러 세대 주택", use: "다세대주택", ic: "home" },
  { t: "그 외 (직접 입력)", d: "예: 수영장·학원·미용실·병원…", use: "", ic: "swap" },
];

// ── 진행레일 (실제 4단계) ──
const STAGES = ["주소", "건축물", "AI 진단", "필요 서류"];

// ── STATE ──
const S = { convos: [], active: null, picked: null, kakao: false, kakaoKey: null };
const LS_KEY = "ganeomteo.convos";

const scroll = () => $("#scroll");
const msgs = () => $("#msgs");
function scrollBottom() { requestAnimationFrame(() => { const s = scroll(); if (s) s.scrollTop = s.scrollHeight; }); }

// ============================================================
//  상담기록 영속 (localStorage; 대화·결과·플로우 전체 저장 → 복원 시 재생)
// ============================================================
function persist() {
  try {
    const slim = S.convos.slice(-20).map((c) => ({   // 최근 20건만(용량 보호)
      loc: c.loc, use_type: c.use_type, stage: c.stage, ts: c.ts,
      threadId: c.threadId || null,
      msgs: Array.isArray(c.msgs) ? c.msgs : [],       // 대화 버블(role+html) — openConvo가 재생
      result: c.result || null,                        // 진단 결과(우측 패널 원천)
      trace: Array.isArray(c.trace) ? c.trace.slice(-80) : [],  // 상세 플로우(최근 80 step)
    }));
    localStorage.setItem(LS_KEY, JSON.stringify(slim));
  } catch (e) { /* 저장 실패(용량 등) 무시 */ }
}
function restore() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return;
    const slim = JSON.parse(raw);
    if (Array.isArray(slim)) S.convos = slim.map((c) => ({
      ...c,
      msgs: Array.isArray(c.msgs) ? c.msgs : [],
      trace: Array.isArray(c.trace) ? c.trace : [],
      restored: true,
    }));
  } catch (e) { S.convos = []; }
}

// ============================================================
//  사이드바 / 온보딩
// ============================================================
function renderSidebar() {
  const list = $("#convList");
  if (!list) return;
  if (!S.convos.length) { list.innerHTML = '<div class="sb-empty">아직 상담이 없어요.<br>‘새 상담 시작’을 눌러 땅 주소를 선택하면 상담이 만들어집니다.</div>'; return; }
  list.innerHTML = "";
  S.convos.forEach((c) => {
    const it = el("button", "sb-item" + (c === S.active ? " active" : "") + (c._new ? " just-added" : ""));
    const st = c.stage != null ? c.stage : 0;
    const pct = Math.round((Math.min(st, STAGES.length - 1) / (STAGES.length - 1)) * 100);
    const complete = st >= STAGES.length - 1;
    const label = complete ? "진단 완료" : (STAGES[st + 1] || STAGES[st] || "") + " 진행 중";
    it.innerHTML = `<span class="pin">${I.pin}</span><span class="meta"><span class="ttl">${esc(c.loc.address)}</span><span class="zone">${esc(c.loc.zone || "용도지역 확인 전")} · ${esc(c.loc.jimok || "지목 확인 전")}</span>`
      + `<span class="sb-prog"><span class="sb-bar"><span style="width:${pct}%"></span></span><span class="sb-stage${complete ? " done" : ""}">${complete ? I.check + " 진단 완료" : esc(label)}</span></span></span>`;
    it.onclick = () => openConvo(c);
    list.appendChild(it);
    c._new = false;
  });
}

function showOnboard() {
  S.active = null;
  const mt = $("#mbarTitle"); if (mt) mt.textContent = "가늠터";
  $("#mbarChange") && $("#mbarChange").classList.add("hidden");
  $("#chead").classList.add("hidden");
  $("#composerWrap").classList.add("hidden");
  $("#prail") && $("#prail").classList.add("hidden");
  scroll().innerHTML = `
    <div class="onboard">
      <div class="ob-grid"></div>
      <div class="ob-inner">
        <div class="ob-badge st1"><span class="dot"></span>가늠터 · AI 사전검토</div>
        <div class="ob-mark st2"><div class="ring"></div><div class="core"><img src="assets/ganeumi-wave.png" alt="가늠이" class="ob-char" /></div></div>
        <h1 class="st3">안녕하세요, 가늠이예요!<br><span class="em">땅 주소만 알려주세요</span></h1>
        <p class="st4">가늠터는 <b>주소를 기준으로</b> 건축 인허가를 미리 가늠해 드려요.<br>먼저 지도에서 땅을 고르면, <br>제가 가능 여부부터 필요한 서류까지 안내할게요.</p>
        <div class="ob-journey st5">
          <div class="ob-jstep"><div class="jn">${I.pin}</div><div class="jt">지도에서<br>주소 선택</div></div>
          <div class="ob-jconn"></div>
          <div class="ob-jstep"><div class="jn">${I.home}</div><div class="jt">건축물·규모<br>입력</div></div>
          <div class="ob-jconn"></div>
          <div class="ob-jstep"><div class="jn">${I.sparkle.replace('width="14" height="14"', 'width="20" height="20"')}</div><div class="jt">AI 진단<br>·필요 서류</div></div>
        </div>
        <button class="ob-cta st6" id="obStart">${I.plus} 새 상담 시작하기</button>
      </div>
    </div>`;
  $("#obStart").onclick = openMap;
  renderSidebar();
}

// ============================================================
//  지도 모달 (카카오 지오코더 — /config 키, 실패 시 폴백 스타일지도)
// ============================================================
function mapBlocks() {
  const b = [[6, 8, 24, 30], [6, 52, 24, 16], [6, 80, 30, 14], [44, 6, 20, 32], [44, 78, 22, 16], [68, 52, 26, 30], [68, 80, 26, 12]];
  return "<div>" + b.map(([l, t, w, h]) => `<div class="map-block" style="left:${l}%;top:${t}%;width:${w}%;height:${h}%"></div>`).join("") + "</div>";
}
function openMap() {
  S.picked = null;
  const ov = $("#overlay");
  ov.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-head">
        <div><div class="mh-t">상담할 땅을 선택해 주세요</div><div class="mh-s">선택한 주소의 규제를 기준으로 AI가 상담해 드려요</div></div>
        <button class="mh-x" id="mapClose" aria-label="닫기">${I.x}</button>
      </div>
      <div class="modal-body">
        <div class="modal-map">
          <div class="map-canvas" id="mapCanvas">
            <div class="map-ground"></div>
            ${mapBlocks()}
            <div class="map-road major" style="left:0;right:0;top:46%;height:24px"></div>
            <div class="map-road" style="left:38%;top:0;bottom:0;width:16px"></div>
            <div class="map-park" style="left:70%;top:12%;width:20%;height:22%"></div>
            <div class="map-park-label" style="left:72%;top:34%">근린공원</div>
            <div class="map-pin hidden" id="mapPin"><svg width="32" height="42" viewBox="0 0 24 30" fill="var(--sky-500)" stroke="#fff" stroke-width="1.5"><path d="M12 1C6.5 1 2 5.5 2 11c0 7 10 18 10 18s10-11 10-18c0-5.5-4.5-10-10-10z"/><circle cx="12" cy="11" r="3.6" fill="#fff" stroke="none"/></svg><div class="ping"></div></div>
            <div class="map-hint">${I.cross} 지도를 클릭해 위치를 선택하세요</div>
          </div>
        </div>
        <div class="modal-side">
          <div class="m-search">
            <div class="si">${I.search}<input id="addrInput" placeholder="도로명·지번 주소 검색" autocomplete="off" /></div>
            <div class="m-suggest hidden" id="suggest"></div>
          </div>
          <button class="m-here" id="hereBtn">${I.cross} 현재 위치로 찾기</button>
          <div class="m-summary" id="mSummary">
            <div class="m-empty"><svg width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg><div style="font-size:14.5px;font-weight:600">위치를 선택해 주세요</div><div style="font-size:13px;margin-top:3px">지도 클릭 · 주소 검색 · 현재 위치</div></div>
          </div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-soft" id="mapCancel">취소</button>
        <button class="btn btn-primary" id="mapConfirm" disabled>이 주소로 상담 시작 ${I.arrow}</button>
      </div>
    </div>`;
  ov.classList.add("show");

  // 폴백 스타일지도 인터랙션 (카카오 미로드 시)
  const canvas = $("#mapCanvas"), pin = $("#mapPin");
  const place = (x, y) => { pin.style.left = Math.max(6, Math.min(94, x)) + "%"; pin.style.top = Math.max(12, Math.min(92, y)) + "%"; pin.classList.remove("hidden"); };
  canvas.onclick = (e) => { const r = canvas.getBoundingClientRect(); place((e.clientX - r.left) / r.width * 100, (e.clientY - r.top) / r.height * 100); pickFallback(); };
  $("#hereBtn").onclick = () => { place(52, 50); pickFallback(); };
  const inp = $("#addrInput");
  inp.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); const v = inp.value.trim(); if (v) { place(46, 48); pickReal(v, ""); } } };

  $("#mapClose").onclick = $("#mapCancel").onclick = closeMap;
  $("#mapConfirm").onclick = confirmMap;
  initKakaoMap();
}

// 폴백: 주소를 직접 못 받는 경우 — 사용자에게 입력 안내(가짜 주소 금지)
function pickFallback() {
  $("#mSummary").innerHTML = `
    <div class="m-card">
      <div class="mc-pin">${I.pin} 위치 선택됨</div>
      <div class="mc-addr">주소를 직접 입력해 주세요</div>
      <div class="mc-road">지도 SDK를 불러오지 못해 좌표→주소 변환을 할 수 없어요. 위 검색창에 도로명·지번 주소를 입력하고 Enter를 눌러주세요.</div>
    </div>`;
  $("#mapConfirm").disabled = true;
}

function pickReal(addr, road) {
  S.picked = { address: addr, road: road || "" };
  $("#mSummary").innerHTML = `
    <div class="m-card">
      <div class="mc-pin">${I.pin} 선택한 위치</div>
      <div class="mc-addr">${esc(addr)}</div>
      <div class="mc-road">${road ? "도로명 " + esc(road) : "지번/도로명 주소"}</div>
      <div class="m-regs"><div class="mr-h">${I.info} 이 주소로 상담을 시작하면, 가늠이가 입지·규제를 실시간으로 조회해요.</div></div>
    </div>`;
  $("#mapConfirm").disabled = false;
}

function initKakaoMap() {
  if (!(window.kakao && window.kakao.maps && kakao.maps.load)) return; // SDK 미로드 → 폴백 유지
  try {
    kakao.maps.load(function () {
      try {
        const canvas = document.getElementById("mapCanvas");
        if (!canvas || !kakao.maps.services) return;
        canvas.onclick = null;
        canvas.innerHTML = "";
        canvas.style.cursor = "default";
        const center = new kakao.maps.LatLng(37.5112, 127.0327);
        const map = new kakao.maps.Map(canvas, { center: center, level: 3 });
        const geocoder = new kakao.maps.services.Geocoder();
        const marker = new kakao.maps.Marker({ map: map, position: center });
        marker.setMap(null);
        const hint = document.createElement("div");
        hint.className = "map-hint"; hint.innerHTML = I.cross + " 지도를 클릭해 위치를 선택하세요";
        canvas.appendChild(hint);

        function setFromCoord(latlng) {
          marker.setPosition(latlng); marker.setMap(map);
          geocoder.coord2Address(latlng.getLng(), latlng.getLat(), function (res, status) {
            if (status === kakao.maps.services.Status.OK && res[0]) {
              const r = res[0];
              const jibun = r.address ? r.address.address_name : "";
              const road = r.road_address ? r.road_address.address_name : "";
              pickReal(jibun || road, road || jibun);
            } else { pickFallback(); }
          });
        }
        kakao.maps.event.addListener(map, "click", function (e) { setFromCoord(e.latLng); });

        const inp = document.getElementById("addrInput"), sg = document.getElementById("suggest");
        inp.onkeydown = null;
        const runSearch = (q) => {
          if (!q) { sg.classList.add("hidden"); return; }
          geocoder.addressSearch(q, function (res, status) {
            if (status === kakao.maps.services.Status.OK && res.length) {
              sg.innerHTML = res.slice(0, 5).map((d, i) => `<button type="button" data-i="${i}">${I.pin}${esc(d.road_address ? d.road_address.address_name : d.address_name)}</button>`).join("");
              sg.classList.remove("hidden");
              $$("button", sg).forEach((b) => b.onclick = () => {
                const d = res[+b.dataset.i]; const ll = new kakao.maps.LatLng(d.y, d.x);
                map.setCenter(ll); marker.setPosition(ll); marker.setMap(map);
                sg.classList.add("hidden"); inp.value = b.textContent.trim();
                pickReal(d.address_name, d.road_address ? d.road_address.address_name : "");
              });
            } else { sg.classList.add("hidden"); }
          });
        };
        let t; inp.oninput = () => { clearTimeout(t); t = setTimeout(() => runSearch(inp.value.trim()), 300); };
        inp.onkeydown = (ev) => { if (ev.key === "Enter") { ev.preventDefault(); runSearch(inp.value.trim()); } };
        const here = document.getElementById("hereBtn");
        here.onclick = () => {
          if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
              (p) => { const ll = new kakao.maps.LatLng(p.coords.latitude, p.coords.longitude); map.setCenter(ll); setFromCoord(ll); },
              () => setFromCoord(center));
          } else setFromCoord(center);
        };
        S.kakao = true;
        window.__kmap = map;
      } catch (e) { /* 인증·도메인 실패 → 폴백 지도 유지 */ }
    });
  } catch (e) { /* 폴백 유지 */ }
}

function closeMap() { $("#overlay").classList.remove("show"); setTimeout(() => { $("#overlay").innerHTML = ""; }, 240); }
function confirmMap() { if (!S.picked) return; const loc = { address: S.picked.address, road: S.picked.road, jimok: "", zone: "" }; closeMap(); createConvo(loc); }

// ============================================================
//  채팅방 생성 / 열기
// ============================================================
function createConvo(loc) {
  const c = { loc, msgs: [], use_type: null, threadId: null, _new: true, started: false, stage: 0, ts: Date.now(), result: null, trace: [] };
  S.convos.unshift(c);
  openConvo(c);
  persist();
  startConsult(c);
}
function openConvo(c) {
  S.active = c;
  closePanel();           // 상담 전환 시 패널 닫고(필요하면 결과 버튼으로 재오픈)
  $("#chead").classList.remove("hidden");
  $("#composerWrap").classList.remove("hidden");
  const L = c.loc;
  const sub = [L.zone, L.jimok].filter(Boolean);
  $("#chead").querySelector(".addr").innerHTML = `<div class="ac-ic">${I.pin}</div><div><div class="ac-t">${esc(L.address)}</div><div class="ac-s">${sub.length ? sub.map((x) => `<span>${esc(x)}</span>`).join('<span class="dotsep">·</span>') : '<span>입지·규제는 진단 중 조회돼요</span>'}</div></div>`;
  updateHeadResultBtn(c);
  $("#cmpAddr").innerHTML = `${I.pin} ${esc(L.address)} 기준으로 상담 중`;
  const mt = $("#mbarTitle"); if (mt) mt.textContent = L.address;
  $("#mbarChange") && $("#mbarChange").classList.remove("hidden");
  if (window.__closeDrawer) window.__closeDrawer();
  renderMsgs(c);
  setStage(c.stage != null ? c.stage : 0);
  // 복원된(메시지 없는) 상담을 열면 결과만 다시 표시 시도
  if (c.restored && !c.msgs.length) {
    msgs().innerHTML = `<div class="msg ai"><div class="av"></div><div class="col"><div class="who">가늠이</div><div class="bubble">이전 상담 기록이에요. 같은 주소로 다시 진단하려면 아래에 건축 행위를 입력하거나 ‘주소 변경’으로 새 상담을 시작하세요.</div></div></div>`;
    if (c.use_type) { pushAINode(quickActions()); }
  }
  renderSidebar();
  wireTerms();
  scrollBottom();
}

// ============================================================
//  메시지 헬퍼
// ============================================================
function appendRaw(m) {
  if (!msgs()) return;
  if (m.role === "node") { msgs().insertAdjacentHTML("beforeend", `<div class="msg ai"><div class="av"></div><div class="col"><div class="who">가늠이</div>${m.html}</div></div>`); wireDynamic(); return; }
  const cls = m.role === "user" ? "user" : "ai";
  msgs().insertAdjacentHTML("beforeend", `<div class="msg ${cls}"><div class="av">${cls === "user" ? "나" : ""}</div><div class="col"><div class="who">${cls === "user" ? "나" : "가늠이"}</div><div class="bubble">${m.html}</div></div></div>`);
}
function pushUser(text) { const m = { role: "user", html: esc(text) }; S.active.msgs.push(m); appendRaw(m); scrollBottom(); }
function pushAINode(html) { const m = { role: "node", html }; S.active.msgs.push(m); appendRaw(m); scrollBottom(); wireTerms(); }

// c.msgs 전체를 DOM에 재렌더(전환 복귀·완료 동기화). 스트리밍 중이면 '분석 중' 라이브 표시 추가.
function renderMsgs(c) {
  scroll().innerHTML = '<div class="msgs" id="msgs"></div>';
  c.msgs.forEach((m) => appendRaw(m));
  if (c._streaming) {
    msgs().insertAdjacentHTML("beforeend",
      `<div class="msg ai" id="liveStream"><div class="av"></div><div class="col"><div class="who">가늠이</div><div class="bubble thinking-bubble"><span class="think-spin"></span><span class="tb-t">분석 중…</span><button class="am-open tb-live" data-act="openpanel">${I.route} 사고과정 보기</button></div></div></div>`);
    wireDynamic();
  }
  wireTerms(); scrollBottom();
}
async function aiSay(html, delay = 600) {
  const wrap = el("div", "msg ai");
  wrap.innerHTML = `<div class="av"></div><div class="col"><div class="who">가늠이</div><div class="bubble"><div class="typing"><span></span><span></span><span></span></div></div></div>`;
  msgs().appendChild(wrap); scrollBottom();
  await wait(delay);
  wrap.querySelector(".bubble").innerHTML = html;
  S.active.msgs.push({ role: "ai", html });
  scrollBottom(); wireTerms();
}

// ============================================================
//  진행레일
// ============================================================
function renderRail() {
  const r = $("#prail"); if (!r) return;
  r.innerHTML = `<div class="prail-inner">${STAGES.map((s, i) => `<div class="pstep${i === STAGES.length - 1 ? " final" : ""}" data-i="${i}"><span class="pdot">${i === STAGES.length - 1 ? I.check : (i + 1)}</span><span class="pname">${esc(s)}</span></div>`).join('<span class="pline"></span>')}</div>`;
}
function setStage(idx) {
  if (S.active) { S.active.stage = idx; persist(); }
  const r = $("#prail"); if (!r) return;
  r.classList.remove("hidden");
  const steps = $$(".pstep", r), lines = $$(".pline", r);
  const last = STAGES.length - 1;
  steps.forEach((s, i) => {
    const isFinalReached = i === last && idx >= last;
    s.classList.toggle("done", i < idx || isFinalReached);
    s.classList.toggle("active", i === idx && !isFinalReached);
  });
  lines.forEach((l, i) => l.classList.toggle("done", i < idx));
  renderSidebar();
}

// ============================================================
//  상담 흐름
// ============================================================
async function startConsult(c) {
  c.started = true;
  setStage(0);
  await wait(300);
  await aiSay(`<b>${esc(c.loc.address)}</b> 기준으로 인허가 상담을 시작할게요.<br>이 땅에서 어떤 건축 행위를 검토하고 계신가요? 아래에서 고르거나 직접 입력해 주세요.`, 700);
  pushAINode(quickActions());
}
function quickActions() {
  return `<div class="qa-wrap" data-role="qa">${ACTIONS.map((a) => `<button class="qa" data-use="${esc(a.use)}" data-name="${esc(a.t)}"><span class="qi">${I[a.ic] || I.home}</span><span><span style="display:block;font-weight:700">${esc(a.t)}</span><span class="qd">${esc(a.d)}</span></span><span class="qg">${I.arrow}</span></button>`).join("")}</div>`;
}

// 건축 행위 선택 → 바로 진단 시작(연면적·층수 강제 안 함 — 에이전트가 판정에 필요할 때 HITL로 요청)
async function chooseUse(useType, name, skipPush) {
  $$('[data-role="qa"]').forEach((n) => { const m = n.closest(".msg"); (m || n).remove(); });
  if (S.active.msgs) S.active.msgs = S.active.msgs.filter((m) => !(m.role === "node" && /data-role="qa"/.test(m.html)));
  S.active.use_type = useType; persist();
  if (!skipPush) pushUser(name);
  setStage(2);
  await wait(150);
  // '조사 시작' 단정 메시지 제거 — 입력이 용도 아닐 수도(에이전트가 되물을 수). 검토 버블이 진행을 표시(모순 방지)
  startDiagnose(S.active);
}

// 진단 시작 — 주소+용도만 전송(면적·층수 미정; 에이전트가 규모·작성주체·주차 판정에 필요하면 request_human_input으로 요청)
function startDiagnose(c) {
  setStage(2);
  const qs = new URLSearchParams({ address: c.loc.address, use_type: c.use_type || "" });   // 빈 용도를 디폴트로 날조하지 않음 — 비우면 에이전트가 되물음(코드 가정 금지)
  runDiagnoseStream("/diagnose/stream?" + qs.toString());
}

// ============================================================
//  진단 스트림 (실 SSE)
//  ChatGPT식: 채팅엔 접힌 "검토 중…" 1개(현재 단계 1줄만 subtle 업데이트).
//  도구호출·사고·근거 등 모든 trace 이벤트는 c.trace[]에 모아 우측 패널용으로만 사용.
// ============================================================
// 스트림 핸들(EventSource)은 전역이 아니라 방별 c._es로 귀속 — 방 전환해도 타 방 스트림 안 죽음(검수 EF-1)

// SSE 이벤트 1건을 c.trace에 누적(채팅엔 렌더 안 함). 우측 '상세 플로우' 원천.
function pushTrace(c, ev) {
  if (!c) return;
  if (!Array.isArray(c.trace)) c.trace = [];
  c.trace.push({ kind: ev.kind, node: ev.node || null, label: ev.label || "", detail: ev.detail || null });
  // 사고과정 패널이 열려있으면 라이브 갱신(ChatGPT식 실시간 추론) — 최신 step으로 스크롤
  const p = $("#resultPanel");
  if (p && p.classList.contains("open") && c === S.active) { renderPanel(c); const b = $("#rpBody"); if (b) b.scrollTop = b.scrollHeight; }
}

// 채팅의 접힌 "검토 중" 상태 버블 생성 → 핸들 반환(현재 1줄 갱신 / 답변으로 교체).
function makeThinking() {
  const wrap = el("div", "msg ai");
  wrap.innerHTML = `<div class="av"></div><div class="col"><div class="who">가늠이</div>`
    + `<div class="bubble thinking-bubble"><span class="think-spin"></span><span class="tb-t">검토 중…</span><span class="tb-step"></span><button class="am-open tb-live" data-act="openpanel">${I.route} 사고과정 보기</button></div></div>`;
  msgs().appendChild(wrap); wireDynamic(); scrollBottom();
  const stepEl = wrap.querySelector(".tb-step");
  return {
    wrap,
    // 현재 단계 1줄만 subtle 교체(누적 나열 금지)
    step(label) { if (label && stepEl) { stepEl.textContent = String(label); scrollBottom(); } },
    // 멈춤 표시(에러/중단 시 — 답변 교체 전 잠깐)
    stop(ok) {
      const sp = wrap.querySelector(".think-spin"); if (sp) sp.remove();
      const t = wrap.querySelector(".tb-t"); if (t) t.textContent = ok ? "검토를 마쳤어요" : "검토를 멈췄어요";
    },
    // 이 상태 버블을 제거(자리비움) — 그 자리에 답변 메시지가 들어감
    remove() { wrap.remove(); },
    // 진단 done → 라이브 버블을 '🤔 검토 완료 · N단계 [자세히 보기]' 칩으로 교체. 자세히=우측 생각과정 사이드바. c.msgs에 기록(복원 재생).
    done(c) {
      const n = Array.isArray(c && c.trace) ? c.trace.length : 0;
      const html = `<div class="bubble think-done">검토 완료${n ? ` · ${n}단계` : ""} <button class="am-open" data-act="openpanel">${I.route} 자세히 보기</button></div>`;
      const col = wrap.querySelector(".col");
      if (col) { const who = col.querySelector(".who"); col.innerHTML = ""; if (who) col.appendChild(who); col.insertAdjacentHTML("beforeend", html); }
      wireDynamic();
      if (c && Array.isArray(c.msgs)) c.msgs.push({ role: "node", html });
    },
  };
}

// SSE 한 이벤트 처리(stream/resume 공용): trace 누적 + 채팅 1줄 갱신. true=종료처리됨.
function handleTraceEvent(c, ev, think) {
  const k = ev && ev.kind;
  if (!k) return false;
  if (k === "meta") { if (ev.detail && ev.detail.thread_id) c.threadId = ev.detail.thread_id; pushTrace(c, ev); think.step("접수 중…"); return false; }
  if (k === "thinking" || k === "tool_call" || k === "tool_result" || k === "citation" || k === "node_done" || k === "verdict" || k === "abstain" || k === "error") {
    pushTrace(c, ev);
    // 채팅엔 현재 단계 1줄만(도구 라벨/사고 머리말) — 20줄 나열 금지
    if (k === "tool_result") { if (ev.detail && ev.detail.found === false) think.step((ev.label || "결과") + " — 확인필요"); }
    else if (k === "thinking") { think.step(_q(ev.detail && ev.detail.text, 40)); }
    else if (k === "error") { think.step(ev.label || "오류"); }
    else think.step(ev.label || k);
    return false;
  }
  return false; // interrupt/done은 호출부에서 처리
}
function _q(s, n) { s = String(s == null ? "" : s).replace(/\s+/g, " ").trim(); return s.length > n ? s.slice(0, n) + "…" : s; }

function runDiagnoseStream(url, followup) {
  const c = S.active;
  if (c._es) { try { c._es.close(); } catch (e) {} c._es = null; }   // 이 방의 기존 스트림만 닫음(타 방 보존)
  if (!followup) { c.trace = []; c.result = null; }   // 후속질문이면 기존 진단 결과·트레이스 유지
  c._streaming = true;   // 진행중 표시 — 다른 방 갔다 와도 openConvo가 '분석 중' 복원
  const think = makeThinking();
  c._think = think;

  const es = new EventSource(url); c._es = es;
  es.onmessage = (e) => {
    let ev; try { ev = JSON.parse(e.data); } catch (_) { return; }
    const k = ev && ev.kind;
    if (!k) return;
    if (k === "interrupt") { try { es.close(); } catch (_) {} c._es = null; c._streaming = false; showInterrupt(ev.detail, think, c); return; }
    if (k === "done") { try { es.close(); } catch (_) {} c._es = null; pushTrace(c, ev); fetchResult(c, think, followup); return; }
    handleTraceEvent(c, ev, think);
  };
  es.onerror = () => {
    if (!c._es) return;   // interrupt/done 핸들러가 이미 의도적으로 닫음(c._es=null) → 무시. 일시정지(HITL interrupt)를 결과실패로 오인해 fetchResult하던 버그 차단('결과를 불러오지 못했어요')
    try { c._es.close(); } catch (_) {} c._es = null;
    // 진짜 연결 끊김만 여기 도달 — 결과 있으면 표시, 아니면 안내(보고 있는 방일 때만 — 검수 EF-5)
    if (c.threadId) fetchResult(c, think, followup);
    else { c._streaming = false; if (c === S.active) { think.remove(); aiSay("진단 연결이 끊어졌어요. 잠시 후 ‘주소 변경’으로 다시 시도하거나 입력을 확인해 주세요.", 400); } }
  };
}

// 인터럽트(HITL) — fields 인라인 입력 → /diagnose/resume.
// 접힌 검토버블은 그대로 두고(자리 유지), 입력폼만 별도 AI 노드로 노출(대화 인터랙션).
function showInterrupt(detail, think, c) {
  c = c || S.active;   // 스트림 소유 방 — SSE 비동기 도착 때 다른 방 보고 있어도 올바른 방에 부착(검수 EF-3)
  detail = detail || {};
  pushTrace(c, { kind: "interrupt", node: null, label: "사용자 입력 필요", detail });
  if (think) think.step("답변을 기다리는 중…");
  // 폼 대신 대화형 — 에이전트 질문을 채팅 버블로, 사용자가 채팅에 자유롭게 답하면 resume(LLM이 해석)
  const q = String(detail.question || "조금 더 알려주실 수 있을까요?");
  const html = formatQuestion(q)
    + `<div class="hitl-hint">${I.info} 아래 채팅창에 편하게 답해 주세요. 그만하려면 “중단”이라고 입력하면 돼요.</div>`;
  c.msgs.push({ role: "ai", html });
  if (c === S.active) { appendRaw({ role: "ai", html }); scrollBottom(); wireTerms(); }   // 보고 있는 방일 때만 DOM
  c._hitl = { thread_id: c.threadId, think };   // 다음 채팅 입력을 resume로 라우팅(freeReply가 봄)
}

function formatQuestion(q) {
  const s = String(q || "").replace(/\r/g, "").trim();
  const parts = [...s.matchAll(/(?:^|\s)([①②③④⑤⑥⑦⑧⑨⑩])\s*([\s\S]*?)(?=\s[①②③④⑤⑥⑦⑧⑨⑩]\s*|$)/g)];
  if (parts.length >= 2) {
    return `<div class="hitl-q-intro">서류 해당 여부를 확정하려고 몇 가지만 알려주세요.</div><ol class="hitl-list">`
      + parts.map((m) => `<li>${linkifyTerms(m[2].trim())}</li>`).join("")
      + `</ol>`;
  }
  return `<div class="hitl-q">${linkifyTerms(s).replace(/\n/g, "<br>")}</div>`;
}

// resume도 같은 검토버블에 이어붙임(trace 누적 + 1줄 갱신).
function resumeStream(url, think) {
  const c = S.active;
  if (c._es) { try { c._es.close(); } catch (e) {} c._es = null; }
  if (!think || !think.wrap || !think.wrap.isConnected) think = c._think = makeThinking();
  c._streaming = true;
  const es = new EventSource(url); c._es = es;
  es.onmessage = (e) => {
    let ev; try { ev = JSON.parse(e.data); } catch (_) { return; }
    const k = ev && ev.kind; if (!k) return;
    if (k === "interrupt") { try { es.close(); } catch (_) {} c._es = null; c._streaming = false; return showInterrupt(ev.detail, think, c); }
    if (k === "done") { try { es.close(); } catch (_) {} c._es = null; pushTrace(c, ev); return fetchResult(c, think); }
    handleTraceEvent(c, ev, think);
  };
  es.onerror = () => { if (!c._es) return; try { c._es.close(); } catch (_) {} c._es = null; if (c.threadId) fetchResult(c, think); else c._streaming = false; };
}

// ============================================================
//  결과 fetch → verdict-card + doc-cards
// ============================================================
async function fetchResult(c, think, followup) {
  if (!c || !c.threadId) { if (think) think.remove(); return; }
  let j;
  try {
    const r = await fetch("/diagnose/result?thread_id=" + encodeURIComponent(c.threadId));
    if (!r.ok) throw new Error("HTTP " + r.status);   // 4xx/5xx 본문을 정상 JSON처럼 처리하던 것 차단(검수 EF-8)
    j = await r.json();
  } catch (e) { if (think) think.remove(); await aiSay("결과를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.", 400); return; }
  c._streaming = false;                 // 진행 종료
  const live = (c === S.active);         // 지금 이 방을 보고 있나 — DOM 갱신은 이때만
  const _ret = j._return || {};
  if (_ret.terminal_reason === "llm_error" || _ret.terminal_reason === "context_overflow") {   // LLM 실패/컨텍스트 초과 — 반쪽 결과 대신 '다시하기'(백엔드 status=재시도필요)
    if (think) think.remove();
    const html = `<div class="retry-box"><span class="rb-msg">${I.bang} 일시적 오류로 분석을 마치지 못했어요.</span><button class="retry-btn" data-act="retry">${I.route} 다시 진단</button></div>`;
    c.msgs.push({ role: "node", html });
    c.result = null; persist();
    if (live) { appendRaw({ role: "node", html }); scrollBottom(); }
    return;
  }
  if (_ret.status === "대화" || _ret.chat) {   // 클로드식 트리아지 — 대화 응답(인사·잡담·되물음). 백엔드 flag만(휴리스틱 0)
    if (think) think.remove();
    const chatHtml = mdLite(_ret.chat || "무엇을 어디에 짓고 싶으신지 알려주세요.");
    c.msgs.push({ role: "ai", html: chatHtml });
    if (!followup) { c.use_type = ""; c.result = null; }   // 후속질문이면 기존 진단 결과 유지(질문 답만 추가)
    persist();
    if (live) { if (think && think.wrap && think.wrap.isConnected) { appendRaw({ role: "ai", html: chatHtml }); scrollBottom(); wireTerms(); } else renderMsgs(c); }
    return;
  }
  c.result = j;                         // 실제 진단 결과만 c.result 갱신(대화는 위에서 return → 후속질문 시 기존 카드 유지)
  // 입지 메타 반영(state는 항상)
  if (j.zone) c.loc.zone = j.zone;
  if (j.jimok) c.loc.jimok = j.jimok;
  c.stage = 3;
  if (think) think.done(c);             // '검토 완료' 칩 → c.msgs(state). wrap 연결 시 DOM도 전환.
  const answerHtml = answerMessage(c);
  c.msgs.push({ role: "node", html: answerHtml });
  persist();                            // 답변·결과·생각과정 영속(새로고침/재방문 복원)
  if (live) {                           // 보고 있을 때만 DOM 갱신
    if (think && think.wrap && think.wrap.isConnected) { appendRaw({ role: "node", html: answerHtml }); scrollBottom(); wireTerms(); }
    else renderMsgs(c);                 // 전환 갔다온 경우 c.msgs로 통째 재렌더(불일치·중복 방지)
    setStage(3);
    updateHeadResultBtn(c);
    const sub = [c.loc.zone, c.loc.jimok].filter(Boolean);
    const acs = $("#chead .ac-s"); if (acs && sub.length) acs.innerHTML = sub.map((x) => `<span>${esc(x)}</span>`).join('<span class="dotsep">·</span>');
    renderPanel(c);
  }
}

// verdict tone → 한 줄 판정 표현(과적합 아님, classifyVerdict 결과만 사용)
function verdictTail(cls) {
  if (cls.tone === "affirmative") return "이에요";
  if (cls.tone === "conditional") return " — 조건을 갖추면 가능해요";
  if (cls.tone === "danger") return " — 신중히 검토해야 해요";
  return " — 직접 확인이 필요한 항목이 있어요";
}

// 진단 done → 채팅 'AI 답변 메시지': 판정 한 줄 + 대화체 2~3줄 요약(legal_reasoning) + '자세히 보기' 1개.
// 카드 전체 덤프 금지(전체 분해는 우측 패널).
function answerMessage(c) {
  const env = (c.result && c.result._return) || {};
  const card = env.card || {};
  const cls = classifyVerdict(card.verdict);
  const level = cls.tone === "affirmative" ? "go" : (cls.tone === "conditional" || cls.tone === "danger") ? "cond" : "check";
  const what = c.use_type ? esc(c.use_type) : "이 건축 행위";
  // 판정 한 줄: "이 땅에 카페는 조건부 가능이에요"
  const headline = `이 땅에 <b>${what}</b>는 <b>${esc(cls.label)}</b>${verdictTail(cls)}`;
  // 대화체 요약 2~3줄: legal_reasoning에서 핵심 근거 1~2 + 다음 할 일 1
  const lines = answerSummaryLines(card, env, c.result);
  const body = lines.map((t) => `<div class="am-line">${t}</div>`).join("");
  // 결과 상세는 채팅 답변 안에 인라인(접힘) — 우측 사이드바는 생각과정만
  const cits = arr(c.result && c.result.citations);
  const detail =
    verdictCard(env, card, cits, c.result) +
    documentFactsCard(card) +
    envelopeCard(card) + leviesCard(card) + parkingCard(card) +
    procedureStepsCard(card) +
    `<div class="rp-sec-h">${I.list} 단계별 제출 서류</div>` + docCards(card);
  return `<div class="answer-msg ${level}" data-role="answer">
    <div class="am-head"><span class="am-sig">${level === "go" ? I.go : level === "cond" ? I.cond : I.info}</span><span class="am-verdict">${headline}</span></div>
    ${body ? `<div class="am-body">${body}</div>` : ""}
    <button class="am-open" data-act="toggle-detail">${I.list} 상세 보기</button>
    <div class="am-detail" hidden>${detail}</div>
  </div>`;
}

// 대화체 요약 줄(2~3): 근거(verdict_basis_seq 우선 → 확정 step) + 확인필요/다음 할 일.
function answerSummaryLines(card, env, full) {
  const lr = card.legal_reasoning || {};
  const steps = arr(lr.steps);
  const out = [];
  // 1) 핵심 근거 1~2줄
  const basisSeq = arr(lr.verdict_basis_seq);
  const bySeq = (n) => steps.find((s) => s.seq === n);
  let picks = basisSeq.map(bySeq).filter(Boolean);
  if (!picks.length) picks = steps.filter((s) => s.status === "확정").slice(0, 2);
  picks.slice(0, 2).forEach((s) => {
    const txt = [s.fact, s.infer].filter(Boolean).join(" → ");
    if (txt) out.push(`${maybeTerm(s.kind || "근거")} 기준 ${esc(txt)}`);
    else if (s.kind) out.push(`${maybeTerm(s.kind)} 항목을 확인했어요.`);
  });
  // 보류형(한글키) — legal_reasoning 없을 때 사유 한 줄
  if (!out.length && card["사유"]) {
    const r = Array.isArray(card["사유"]) ? card["사유"].map((x) => x["사유"] || x).join(" / ") : card["사유"];
    out.push(esc(r));
  }
  // 2) 다음 할 일/유의 1줄
  const needs = compactNeedCount(steps);
  if (needs) out.push(`다만 ${needs}개 항목은 추가 확인이 필요해요.`);
  out.push(`자세한 서류·근거·규모·부담금은 아래 ‘상세 보기’에서 확인하세요.`);
  return out.slice(0, 3);
}

// ============================================================
//  우측 결과 패널 (ChatGPT 캔버스식)
// ============================================================
function openPanel() {
  const p = $("#resultPanel"), b = $("#rpBackdrop");
  if (!p) return;
  p.classList.add("open"); p.setAttribute("aria-hidden", "false");
  if (b) b.classList.add("show");
}
function closePanel() {
  const p = $("#resultPanel"), b = $("#rpBackdrop");
  if (!p) return;
  p.classList.remove("open"); p.setAttribute("aria-hidden", "true");
  if (b) b.classList.remove("show");
}
// 헤더에 '결과 보기' 버튼 — result 있을 때만 노출(재오픈용)
function updateHeadResultBtn(c) {
  const head = $("#chead"); if (!head) return;
  let btn = head.querySelector("#headResult");
  const has = !!(c && c.result);
  if (!has) { if (btn) btn.remove(); return; }
  if (!btn) {
    btn = el("button", "change");
    btn.id = "headResult";
    btn.innerHTML = `${I.route} 생각과정`;
    btn.onclick = () => { if (S.active) { renderPanel(S.active); openPanel(); } };
    const change = head.querySelector("#changeAddr");
    if (change) head.insertBefore(btn, change); else head.appendChild(btn);
  }
}

// 주어진 상담의 result를 패널에 렌더(결과 없으면 안내)
// 우측 사이드바 = 가늠이의 생각과정(트레이스)만. 결과(서류·규모·부담금)는 채팅 답변 인라인 '상세 보기'에.
function renderPanel(c) {
  const body = $("#rpBody"); if (!body) return;
  const L = (c && c.loc) || {};
  const ic = $("#rpIcon"), tt = $("#rpTitle"), ss = $("#rpSub");
  if (ic) ic.innerHTML = I.route;
  if (tt) tt.textContent = "생각과정";
  if (ss) ss.textContent = L.address || "";
  if (!c || !arr(c.trace).length) {
    body.innerHTML = `<div class="card card-pad"><p style="font-size:14px;color:var(--fg-3);margin:0;line-height:1.6">${I.info} 이 상담은 생각과정 기록이 아직 없어요. (이전 기록이거나 재진단이 필요해요.)</p></div>`;
    return;
  }
  body.innerHTML =
    `<div class="rp-sec-h">${I.route} 가늠이의 생각과정</div>` +
    flowSection(c);
  wireDynamic();
  wireTerms();
  body.scrollTop = 0;
}

// ── 우측 '상세 추론 과정': c.trace[] step들을 시간순으로(도구호출·결과·🤔사고·근거·판정) ──
function flowSection(c) {
  const tr = arr(c && c.trace);
  if (!tr.length) return `<div class="card card-pad"><p style="font-size:13.5px;color:var(--fg-3);margin:0;line-height:1.6">${I.info} 이 진단의 추론 과정 기록이 없어요. (이전 기록이거나 재진단이 필요해요.)</p></div>`;
  const rows = tr.map((ev) => flowRow(ev)).filter(Boolean).join("");
  return `<div class="flow-list">${rows}</div>`;
}
function flowRow(ev) {
  const k = ev.kind, d = ev.detail || {};
  if (k === "meta") {
    return flowItem("dot", "접수", esc((d.address || "") + (d.use_type ? " · " + d.use_type : "")));
  }
  if (k === "thinking") {
    return flowItem("think", "가늠이의 판단", esc(d.text || ""));
  }
  if (k === "tool_call") {
    const args = d.args && Object.keys(d.args).length ? Object.entries(d.args).map(([kk, vv]) => `${esc(kk)}: ${esc(String(vv))}`).join(" · ") : "";
    return flowItem("call", esc(ev.label || (d.tool || "도구")), args);
  }
  if (k === "tool_result") {
    const ok = d.found !== false;
    return flowItem((ok ? "ok" : "na") + " res", esc(ev.label || "결과") + (ok ? "" : " — 확인필요"), d.quote ? "“" + esc(d.quote) + "”" : (ok ? "결과 확보" : "자동 조회 안 됨"));
  }
  if (k === "citation") {
    const head = [d.law_name, d.article, d.title].filter(Boolean).join(" ") || srcKo(d.source);
    const href = lawHref(d);
    const link = href ? ` <a href="${esc(href)}" target="_blank" rel="noreferrer" class="flow-link">${I.ext} 원문</a>` : "";
    return flowItem("cite", "근거 확보", esc(head) + (d.quote ? " — “" + esc(d.quote) + "”" : "") + link);
  }
  if (k === "node_done") return flowItem("done", esc(ev.label || "단계 완료"), "");
  if (k === "verdict") return flowItem("verdict", esc(ev.label || "1차 판정 도출"), d.verdict ? "판정: " + esc(d.verdict) : "");
  if (k === "abstain") return flowItem("na", esc(ev.label || "자동판정 보류"), "");
  if (k === "interrupt") return flowItem("na", esc(ev.label || "사용자 입력 필요"), esc((d && d.question) || ""));
  if (k === "error") return flowItem("na", esc(ev.label || "오류"), "");
  if (k === "done") return flowItem("ok", esc(ev.label || "진단 완료"), d.terminal_reason ? esc(statusKo(d.terminal_reason)) : "");
  return "";
}
function flowItem(type, title, detail) {
  return `<div class="flow-item ${esc(type)}"><div class="fi-rail"><span class="fi-dot"></span></div>`
    + `<div class="fi-main"><div class="fi-t">${title}</div>${detail ? `<div class="fi-d">${detail}</div>` : ""}</div></div>`;
}

// ── 규모(envelope): scale_limits 신규 필드 — 없으면 graceful skip ──
function envelopeCard(card) {
  const sl = card.scale_limits || {};
  const rows = [];
  if (sl.max_building_area != null) rows.push(["최대 건축면적", esc(sl.max_building_area) + "㎡"]);
  if (sl.max_floor_area != null) rows.push(["최대 연면적", esc(sl.max_floor_area) + "㎡"]);
  if (sl.approx_floors != null) rows.push(["층수 환산(최대)", esc(Math.floor(sl.approx_floors)) + "개 층 (용적률÷건폐율)"]);
  const notes = [];
  if (sl.envelope_note) notes.push(esc(sl.envelope_note));
  if (sl.energy_saving_required) notes.push(maybeTerm("에너지절약계획서") + " 제출 대상이에요.");
  if (sl.structural_safety_required) notes.push(maybeTerm("구조안전확인서") + " 확인 대상이에요.");
  if (!rows.length && !notes.length) return "";
  return `<div class="card card-pad mini-card">
    <div class="card-h" style="padding:0 0 6px">${I.home} 지을 수 있는 규모</div>
    ${rows.length ? `<div class="kv-grid" style="padding:2px 0 ${notes.length ? "10px" : "0"}">${rows.map(([k, v]) => `<div class="kv-cell"><div class="k">${esc(k)}</div><div class="v">${v}</div></div>`).join("")}</div>` : ""}
    ${notes.map((n) => `<div class="mini-note">${I.info}<span>${n}</span></div>`).join("")}
  </div>`;
}

// ── 부담금(levies): 신규·있을 수 있음 — 산식 + amount(있으면 금액, 없으면 확인필요) ──
function leviesCard(card) {
  const lv = arr(card.levies);
  if (!lv.length) return "";
  const rows = lv.map((l) => {
    const has = l.amount != null && l.amount !== "";
    const amt = has ? `<span class="lv-amt">${esc(typeof l.amount === "number" ? l.amount.toLocaleString() : l.amount)}원</span>` : `<span class="lv-amt na">확인 필요</span>`;
    const meta = [l.formula ? "산식 " + esc(l.formula) : "", l.note ? esc(l.note) : ""].filter(Boolean).join(" · ");
    return `<div class="lv-row"><div class="lv-main"><div class="lv-t">${esc(l.levy_type || "부담금")}</div>${meta ? `<div class="lv-m">${meta}</div>` : ""}</div>${amt}</div>`;
  }).join("");
  return `<div class="card card-pad mini-card"><div class="card-h" style="padding:0 0 8px">${I.info} 예상 부담금</div>${rows}</div>`;
}

// ── 확인하신 정보(document_facts): HITL로 사용자가 답한 서류판단 사실(durable) ──
function documentFactsCard(card) {
  const f = card.document_facts;
  if (!f || typeof f !== "object" || !Object.keys(f).length) return "";
  const LBL = { land_ownership: "토지 소유", land_right: "사용 권원", land_tenure: "사용 권원", prior_decision: "사전결정", combined_building_agreement: "결합건축협정", existing_use: "기존 용도", answer: "답변" };
  const label = (k) => LBL[k] || String(k).replace(/_/g, " ");
  const rows = Object.entries(f).map(([k, v]) => {
    if (v == null || v === "" || typeof v === "object") return "";
    return `<div class="kv-cell"><div class="k">${esc(label(k))}</div><div class="v">${esc(String(v))}</div></div>`;
  }).filter(Boolean).join("");
  if (!rows) return "";
  return `<div class="card card-pad mini-card"><div class="card-h" style="padding:0 0 6px">${I.check} 확인하신 정보</div><div class="kv-grid" style="padding:2px 0 0">${rows}</div></div>`;
}

// ── 주차(parking_req): 신규·있을 수 있음 ──
function parkingCard(card) {
  const p = card.parking_req;
  if (!p || typeof p !== "object" || !Object.keys(p).length) return "";
  const rows = Object.entries(p).map(([k, v]) => {
    if (v == null || v === "" || typeof v === "object") return "";
    return `<div class="kv-cell"><div class="k">${esc(k)}</div><div class="v">${esc(String(v))}</div></div>`;
  }).filter(Boolean).join("");
  if (!rows) return "";
  return `<div class="card card-pad mini-card"><div class="card-h" style="padding:0 0 6px">🅿 주차 기준</div><div class="kv-grid" style="padding:2px 0 0">${rows}</div></div>`;
}

// 다차원 판정 축(LLM이 record_verdict로 케이스마다 생성 — 코드 고정목록 없음). 종합 verdict 아래 투명 표시.
function verdictAxes(card) {
  const labels = Array.isArray(card.verdict_labels) ? card.verdict_labels : [];
  if (!labels.length) return "";
  const tone = (s) => (s === "충족" ? "ok" : s === "불가" ? "no" : "mid");
  const rows = labels.map((l) =>
    `<div class="vax ${tone(l.status)}"><span class="vax-s">${esc(l.status || "")}</span><div class="vax-b"><div class="vax-d">${esc(l.dimension || "")}</div><div class="vax-r">${esc(l.reason || "")}</div></div></div>`
  ).join("");
  return `<div class="card-h">${I.list} 판정 축별 결과</div><div class="verdict-axes">${rows}</div>`;
}

// ── verdict-card (level: classifyVerdict.tone → go/cond/check) ──
function verdictCard(env, card, cits, full) {
  const v = card.verdict;
  const cls = classifyVerdict(v);
  const level = cls.tone === "affirmative" ? "go" : (cls.tone === "conditional" || cls.tone === "danger") ? "cond" : "check";
  const sig = level === "go" ? I.go : level === "cond" ? I.cond : I.info;
  const lr = card.legal_reasoning || {};
  const steps = arr(lr.steps);

  // vc-body = 1차판정 사유 요약: verdict_basis_seq의 step infer/fact, 없으면 확인필요 step 사유
  let bodyHtml = bodySummary(card, lr, steps, env);

  // kv-grid: zone·jimok·도로접면(입지 step에서 추출)·규제(첫 reg_effect)
  const kv = [];
  if (full && full.zone) kv.push(["용도지역", maybeTerm("용도지역") + " " + esc(full.zone)]);
  if (full && full.jimok) kv.push(["지목", maybeTerm("지목") + " " + esc(full.jimok)]);
  const road = roadFromSteps(steps);
  if (road) kv.push(["도로접면", maybeTerm("도로접면") + " " + esc(road)]);
  arr(card.reg_effects).slice(0, 1).forEach((r) => { if (r && r.reg_name) kv.push(["중첩 규제", esc(r.reg_name)]); });
  while (kv.length && kv.length < 2) break;

  // check-list: steps (확정→ok, 확인필요→na). 규제효과는 개별 반복 대신 한 줄로 묶고, 상세 근거 펼침에는 원본 step을 유지한다.
  const regSteps = steps.filter((s) => s.kind === "규제효과");
  const viewSteps = steps.filter((s) => s.kind !== "규제효과");
  if (regSteps.length) {
    const pending = regSteps.filter(stepNeedsReview);
    viewSteps.push({
      kind: "규제효과",
      fact: summarizeNames(regSteps),
      status: pending.length ? "확인필요" : "확정",
    });
  }
  const checkRows = viewSteps.map((s) => {
    const ok = s.status === "확정";
    const txt = [s.kind, s.fact].filter(Boolean).join(" · ") || (s.kind || "단계");
    return `<div class="check-row ${ok ? "ok" : "na"}"><span class="ck">${ok ? I.check : I.bang}</span>${esc(txt)}</div>`;
  }).join("");

  // risk-list: abstentions + 확인필요 step + scale_limits.notes
  const risks = [];
  const pendingRegs = regSteps.filter(stepNeedsReview);
  if (pendingRegs.length) {
    const names = summarizeNames(pendingRegs);
    risks.push(["중첩 규제 확인 필요", `${esc(names)}의 세부 효과는 자동으로 확정하지 못했어요. 관할 고시·결정도서·담당 부서 확인이 필요합니다.`, "mid"]);
  }
  const _seenRisk = new Set();
  steps.filter((s) => stepNeedsReview(s) && s.kind !== "규제효과").forEach((s) => {
    const title = `'${s.kind || "단계"}' 추가 확인 필요`;
    const desc = esc(s.infer || s.leads || "이 항목은 자동으로 확정하지 못했어요. 관할 부서·건축사에게 확인하세요.");
    const key = title + "|" + desc;
    if (_seenRisk.has(key)) return;
    _seenRisk.add(key);
    risks.push([title, desc, "mid"]);
  });
  const sl = card.scale_limits || {};
  arr(sl.notes).forEach((n) => risks.push(["규모 기준", esc(n), "low"]));
  if (sl.energy_saving_required) risks.push([maybeTerm("에너지절약계획서") + " 대상", "연면적 기준을 넘어 에너지절약계획서 제출이 필요해요.", "mid"]);
  if (sl.structural_safety_required) risks.push([maybeTerm("구조안전확인서") + " 대상", "연면적·층수 기준에 따라 구조안전 확인이 필요해요.", "mid"]);
  // abstentions: env·card는 동일 리스트라 한 쪽만 렌더(중복 방지) + Set dedup. 내부 제어신호(completeness_guard 스텝캡)는
  //   [node] jargon 없이 평이한 한 줄로 접는다(미판정 항목은 위 '확인 필요'·서류 applies로 이미 노출됨).
  const _seenAb = new Set();
  arr(env.abstentions).forEach((a) => {
    const isGuard = a.node === "completeness_guard";
    const txt = isGuard ? "일부 항목 추가 확인 필요" : "자동판정 보류";
    const desc = isGuard
      ? "자동 판정을 다 마치지 못한 항목이 있어요. 위 ‘확인 필요’ 항목과 제출서류의 해당 여부를 직접 점검하세요."
      : esc(a["사유"] || "");
    const key = txt + "|" + desc;
    if (_seenAb.has(key)) return;
    _seenAb.add(key);
    risks.push([txt, desc, "mid"]);
  });
  const riskHtml = risks.map((r) => `<div class="risk-row ${r[2]}"><div class="rc">${I.bang}</div><div><div class="rt">${r[0]}</div><div class="rd">${r[1]}</div></div></div>`).join("");

  // next-list: 합성(서류 준비 + 관할 문의 + author)
  const next = synthNext(card, full);
  const nextHtml = next.map((n) => `<li>${n}</li>`).join("");

  // 판단 근거 disclose: steps(basis별) + citations(url 링크)
  const discloseHtml = discloseBody(steps, cits);
  const substN = cits.filter((c) => ["law", "ordin", "data"].includes(c.source)).length;
  const discloseN = steps.length + cits.length;

  // 보류 카드(한글키) 방어: legal_reasoning 없고 한글키만 있을 때
  const isAbstainShape = !card.legal_reasoning && (card["입지"] || card["사유"]);

  return `<div class="card verdict-card ${level}">
    <div class="vc-top"><div class="signal">${sig}</div><div><div class="vc-label">AI 사전 진단 · ${esc(statusKo(env.terminal_reason))}</div><div class="vc-title">${esc(cls.label)}</div></div></div>
    <div class="vc-body">${bodyHtml}</div>
    <div class="vc-caveat">${I.info}<span>이건 <b>입력하신 조건 기준의 사전 진단</b>이에요. 최종 허가 여부는 관할 기관 확인이 필요해요.</span></div>
    ${kv.length ? `<div class="kv-grid">${kv.map(([k, val]) => `<div class="kv-cell"><div class="k">${esc(k)}</div><div class="v">${val}</div></div>`).join("")}</div>` : ""}
    ${verdictAxes(card)}
    ${isAbstainShape ? abstainBlock(card) : ""}
    ${checkRows ? `<div class="card-h">${I.list} 검토한 항목</div><div class="check-list">${checkRows}</div>` : ""}
    ${riskHtml ? `<div class="card-h">${I.bang} 미리 알아둘 점</div><div class="risk-list">${riskHtml}</div>` : ""}
    ${nextHtml ? `<div class="card-h">${I.route} 다음에 해야 할 일</div><ol class="next-list">${nextHtml}</ol>` : ""}
    <details class="disclose"><summary>판단 근거 ${discloseN}개 보기 <span class="chev">${I.chev}</span></summary>
      <div class="dbody">${discloseHtml}<div class="cite-meta">법적 근거 ${substN}건${cits.length > substN ? ` · 입지 출처 ${cits.length - substN}건(법적 근거 아님)` : ""}</div></div>
    </details>
  </div>`;
}

// vc-body: 1차판정 사유 요약 (verdict_basis_seq 우선 → 확인필요 step → fallback)
function bodySummary(card, lr, steps, env) {
  const basisSeq = arr(lr.verdict_basis_seq);
  const bySeq = (n) => steps.find((s) => s.seq === n);
  const picks = basisSeq.map(bySeq).filter(Boolean);
  if (picks.length) {
    return picks.map((s) => `<b>${esc(s.kind || "근거")}</b> — ${esc(s.fact || "")}${s.infer ? " · " + esc(s.infer) : ""}`).join("<br>");
  }
  const needs = steps.filter((s) => s.status === "확인필요");
  if (needs.length) {
    return "일부 항목이 <b>자동으로 조회되지 않아</b> ‘확인필요’로 판정했어요. 아래 항목은 발급처·관할에서 직접 확인하세요.<br>" + needs.map((s) => `${esc(s.kind || "단계")}: ${esc(s.infer || s.leads || "직접 확인 필요")}`).join("<br>");
  }
  if (steps.length) return steps.map((s) => `<b>${esc(s.kind)}</b> ${esc(s.fact || "")}`).join("<br>");
  // 보류형 한글키
  if (card["사유"]) return esc(Array.isArray(card["사유"]) ? card["사유"].map((x) => x["사유"] || x).join(" / ") : card["사유"]);
  return "근거가 충분치 않아 자동 판정을 보류했어요. 아래 항목을 확인해 주세요.";
}

function roadFromSteps(steps) {
  const ip = steps.find((s) => s.kind === "입지" || (s.fact && /도로접면/.test(s.fact)));
  if (!ip || !ip.fact) return "";
  const m = String(ip.fact).match(/도로접면=([^\s]+)/);
  if (m) return m[1] === "None" ? "확인필요" : m[1];
  return "";
}

function synthNext(card, full) {
  const out = [];
  const stages = arr(card.documents).map((d) => d.stage || d.stage_key).filter(Boolean);
  if (stages.length) out.push(`아래 단계별 서류 준비: ${esc(stages.join(" → "))}`);
  arr(card.uijae).forEach((u) => { if (u.permit_name) out.push(`의제 검토: ${esc(u.permit_name)}`); });
  const sigungu = full && full.address ? regionOf(full.address) : "";
  out.push(`관할 기관(${esc(sigungu || "해당 시·군·구청 건축과")})에 적용 조례·세부 조건 문의`);
  return out;
}
function regionOf(addr) {
  const m = String(addr).match(/(\S+[시군구])\s/);
  return m ? m[1] + "청" : "";
}

function discloseBody(steps, cits) {
  // basis별: null→근거미확보 / vworld→입지출처(법근거 아님) / law·ordin·data→법적근거
  const stepRows = steps.map((s) => {
    const b = s.basis;
    const cls = !b ? "none" : (b === "vworld" ? "site" : "law");
    const tag = !b ? "자동 조회 안 됨 → 직접 확인 필요" : (b === "vworld" ? "입지 출처(법적 근거 아님)" : "법적 근거: " + esc(b));
    return `<div class="basis-item"><div class="bc">${!b ? I.bang : I.check}</div><div><div class="bt">${maybeTerm(s.kind || "단계")}</div><div class="bd">${linkifyTerms(s.fact || "")}${s.infer ? " — " + linkifyTerms(s.infer) : ""}</div><span class="bsrc bsrc-${cls}">${tag}</span></div></div>`;
  }).join("");
  // citations: 법령 원문 링크(url 있으면), 없으면 law_name으로 law.go.kr
  const citRows = cits.map((c) => {
    const head = [c.law_name, c.article, c.title].filter(Boolean).join(" ") || srcKo(c.source);
    const href = lawHref(c);
    const link = href ? `<a class="law-src" href="${esc(href)}" target="_blank" rel="noreferrer">${I.ext} 법령 원문 보기</a>` : "";
    const badge = c.extract_method ? `<span class="bsrc bsrc-${"law"}">${esc(srcKo(c.source))} · ${esc(c.extract_method)}</span>` : `<span class="bsrc bsrc-${"law"}">${esc(srcKo(c.source))}</span>`;
    return `<div class="law-item"><div class="law-name">${I_law}<span>${esc(head)}</span></div>${c.quote ? `<div class="law-plain">“${esc(c.quote)}”</div>` : ""}${badge}${link}</div>`;
  }).join("");
  return `<div class="basis-wrap">${stepRows}</div>${citRows ? `<div class="law-list" style="margin-top:12px">${citRows}</div>` : ""}`;
}

function abstainBlock(card) {
  const ip = card["입지"] || {};
  const rows = [["지목", ip["지목"]], ["용도지역", ip["용도지역"]], ["도로접면", ip["도로접면"]]]
    .map(([k, v]) => `<div class="kv-cell"><div class="k">${esc(k)}</div><div class="v">${v == null ? "미확보" : esc(v)}</div></div>`).join("");
  return `<div class="kv-grid">${rows}</div>`;
}

// ── 서류 단계 카드 (documents[] → 절차순 + 호별 체크리스트, 목은 들여쓰기) ──
// 목(가/나/다…) 판별: ho에 한글 목문자(가–하 단음절)가 들어가면 목. '1.'·'2.'·'1의2.'엔 없음.
const MOK_RE = /[가나다라마바사아자차카타파하]/;
function isMok(ho) { return MOK_RE.test(String(ho || "")); }

// 제출처 포털 — stage 키워드 기반(가짜 URL 날조 아님, 공식 포털만)
function submitPortal(stage) {
  if (/농지/.test(stage)) return ["정부24(농지전용)", "https://www.gov.kr"];
  return ["세움터(건축행정시스템)", "https://www.eais.go.kr"];
}

// 절차순 정렬: 건축허가 → (의제) → 착공신고 → 사용승인.
// 의제 단계는 card.uijae[].stage_key로 식별(특정 zone/주소 하드코딩 아님).
function orderedDocs(card) {
  const docs = arr(card.documents);
  const uijaeKeys = new Set(arr(card.uijae).map((u) => u && u.stage_key).filter(Boolean));
  const rank = (d) => {
    const s = String(d.stage || d.stage_key || "");
    if (/건축\s*허가|건축허가/.test(s)) return 0;
    if (uijaeKeys.has(s)) return 1;            // 의제(농지전용/산지전용/개발행위 등)
    if (/착공/.test(s)) return 2;
    if (/사용\s*승인|사용승인/.test(s)) return 3;
    return 1.5;                                 // 미분류(혹시 모를 단계) → 의제 뒤
  };
  return docs.map((d, i) => [d, i]).sort((a, b) => (rank(a[0]) - rank(b[0])) || (a[1] - b[1])).map((x) => x[0]);
}

// 한 단계의 첨부서류 items를 item_type(group/doc/spec/cross_ref) 기반으로 렌더 — 주 단계·embed 의제 공용.
// cross_ref는 에이전트 조건부 판정(applies)+assess_reason(멀티홉 해소)을 그대로 태운다(코드가 의제 맵 안 만듦=무하드코딩).
function renderDocItems(items, law, article) {
  const prepHint = (it) => {
    const proviso = it.has_proviso ? " (단서·예외 조건 있음 — 원문 확인)" : "";
    if (it.form_hwp || it.form_pdf) {
      const tip = `정해진 서식이 있어요. 양식(HWP/PDF)을 받아 작성해 제출하세요.${proviso}`;
      return `<span class="ds-form" title="${esc(tip)}">${I.down}<em>양식</em>${it.form_hwp ? `<a href="${esc(it.form_hwp)}" target="_blank" rel="noreferrer">HWP</a>` : ""}${it.form_pdf ? `<a href="${esc(it.form_pdf)}" target="_blank" rel="noreferrer">PDF</a>` : ""}</span>`;
    }
    const tip = `자동으로 찾은 공식 양식 링크가 없어요. ${law}${article ? " " + article : ""} 원문 내용을 확인해 준비하세요.${proviso}`;
    return `<span class="ds-self" title="${esc(tip)}">${I.info}<em>직접 준비</em></span>`;
  };
  const apOf = (it, inherited) => {
    if (it && it.conditional) return it.applies || (inherited && inherited !== "must" ? inherited : "unknown");
    return inherited && inherited !== "must" ? inherited : "must";
  };
  const apBadge = (ap) => ap === "must" ? `<span class="ds-ap ds-ap-m">필수</span>`
    : ap === "yes" ? `<span class="ds-ap ds-ap-y">해당</span>`
    : ap === "no" ? `<span class="ds-ap ds-ap-n">비해당</span>`
    : `<span class="ds-ap ds-ap-u">확인필요</span>`;
  const rowIcon = (ap) => {
    const cls = ap === "no" ? "n" : ap === "unknown" ? "u" : "y";
    const icon = ap === "no" ? I.x : ap === "unknown" ? I.cond : I.check;
    return `<span class="dchk dchk-${cls}">${icon}</span>`;
  };
  const prepFor = (it, ap) => {
    if (ap === "no") return `<span class="ds-off-note">제출 불요</span>`;
    if (ap === "unknown") return `<span class="ds-wait">${I.cond}<em>해당 여부 확인 후 준비</em></span>`;
    return prepHint(it);
  };
  let curGroupAp = null;   // 직전 그룹 헤더 applies(자식 목-doc 상속); null=그룹 문맥 없음
  const rows = arr(items).map((it) => {
    const t = it.item_type || "doc";
    if (t === "application") return { kind: "application", it, ap: "must" };   // 신청서 양식 = 제출묶음의 동등 row(메인/부속 구분 아님)
    if (t === "group") { curGroupAp = apOf(it, "must"); return { kind: "group", it, ap: curGroupAp }; }
    if (t === "cross_ref") { const cap = apOf(it, isMok(it.ho) && curGroupAp ? curGroupAp : "must"); if (!isMok(it.ho)) curGroupAp = null; return { kind: "xref", it, ap: cap }; }
    if (t === "spec") { return { kind: "spec", it }; }
    const child = isMok(it.ho);
    const ap = apOf(it, child && curGroupAp ? curGroupAp : "must");
    if (!child) curGroupAp = null;
    return { kind: "doc", it, ap, child };
  });
  const submit = rows.filter((r) => (r.kind === "doc" || r.kind === "application") && (r.ap === "must" || r.ap === "yes"));
  const check = rows.filter((r) => r.kind === "doc" && r.ap === "unknown");
  const off = rows.filter((r) => r.kind === "doc" && r.ap === "no");
  const xref = rows.filter((r) => r.kind === "xref" && r.ap !== "no");
  const rowHtml = (r) => {
    const nm = String(r.it.doc_name || "").trim();
    if (r.kind === "application") {
      return `<div class="ds-doc ds-doc-apply">${rowIcon("must")}<span class="dtxt">${nm ? esc(nm) : "신청서"}<span class="ds-app-tag">신청서</span></span>${prepHint(r.it)}</div>`;
    }
    if (r.kind === "group") {
      return `<div class="ds-doc ds-group">${rowIcon(r.ap)}<span class="dtxt">${nm ? esc(nm) : "(다음 각 목)"}${apBadge(r.ap)}<span class="ds-group-tag">아래 해당 서류</span></span></div>`;
    }
    if (r.kind === "xref") {   // cross_ref = 관계법령(의제) 위임 — 법조문 텍스트 라벨 대신 명확 라벨 + 해소근거(assess_reason) + 아래 구체 의제서류로(법조문 원문은 hover)
      const areason = r.it.assess_reason ? `<div class="ds-areason">${linkifyTerms(String(r.it.assess_reason))}</div>` : "";
      const hint = r.ap === "no" ? `<span class="ds-off-note">제출 불요</span>`
        : r.ap === "unknown" ? `<span class="ds-wait">${I.cond}<em>해당 여부 확인 후</em></span>`
        : `<span class="ds-xref-to">아래 "함께 첨부 의제 서류"로 제출</span>`;
      return `<div class="ds-doc ds-xref${r.ap === "no" ? " ds-doc-off" : ""}"${nm ? ` title="${esc(nm)}"` : ""}>${rowIcon(r.ap)}<span class="dtxt">관계 인허가(의제)에서 요구하는 제출서류${apBadge(r.ap)}${areason}</span>${hint}</div>`;
    }
    if (r.kind === "spec") {
      return `<div class="ds-mok"><span class="mbar"></span><span class="dtxt">${nm ? esc(nm) : ""}</span></div>`;
    }
    const areason = (r.it.conditional && r.it.assess_reason) ? `<div class="ds-areason">${linkifyTerms(String(r.it.assess_reason))}</div>` : "";
    return `<div class="ds-doc${r.ap === "no" ? " ds-doc-off" : ""}${r.child ? " ds-doc-peer" : ""}">${rowIcon(r.ap)}<span class="dtxt">${nm ? esc(nm) : "(서류명 없음)"}${apBadge(r.ap)}${areason}</span>${prepFor(r.it, r.ap)}</div>`;
  };
  return { html: rows.map(rowHtml).join(""), submit, check, off, xref };
}

// 단계의 신청서 양식(apply_*)을 제출목록 첫 행(item_type=application)으로 — 별도 강조박스 아님, 동등 row.
function _stageItems(d) {
  const app = (d.apply_hwp || d.apply_pdf || d.apply_title)
    ? [{ ho: "", doc_name: d.apply_title || "신청서", item_type: "application", form_hwp: d.apply_hwp || "", form_pdf: d.apply_pdf || "", conditional: false }]
    : [];
  return app.concat(arr(d.items));
}

// 인허가 절차 타임라인(item 17) — card.procedure_steps만 사용(documents서 추론 안 함, 법적 절차 합성 금지). backend 값만 표시.
function procedureStepsCard(card) {
  const steps = arr(card.procedure_steps);
  if (!steps.length) return "";   // 없으면 합성 안 함(프론트가 절차 임의 생성 금지)
  const sorted = steps.slice().sort((a, b) => (a.order || 0) - (b.order || 0));
  const ubBadge = (ub) => ub === "authority" ? `<span class="ps-ub ps-ub-auth">관할 심의/확인</span>`
    : ub === "user" ? `<span class="ps-ub ps-ub-user">사용자 확인</span>`
    : ub === "data_unavailable" ? `<span class="ps-ub ps-ub-na">데이터 부재</span>`
    : ub === "tool_budget_exhausted" ? `<span class="ps-ub ps-ub-cap">추가 조사 한도</span>` : "";
  const stBadge = (s) => s === "근거확보" ? `<span class="ps-st ps-st-ok">근거확보</span>` : `<span class="ps-st ps-st-q">확인필요</span>`;
  let n = 0;
  const rows = sorted.map((p) => {
    const off = (p.applies || "yes") === "no";
    const title = esc(p.title || p.stage_key || p.step_id || "단계");
    const action = p.action || p.when_note || "";
    const meta = [];
    if (p.actor) meta.push("주체 " + esc(p.actor));
    if (p.authority) meta.push("관할 " + esc(p.authority));
    if (p.law_name) meta.push(esc(p.law_name) + (p.article ? " " + esc(p.article) : ""));
    const docN = arr(p.related_document_stage_keys).length;
    if (p.requires_documents && docN) meta.push("연결 서류 " + docN + "단계");
    return `<div class="ps-row${off ? " ps-off" : ""}">
      <div class="ps-num">${off ? "–" : ++n}</div>
      <div class="ps-body">
        <div class="ps-title">${title}${off ? `<span class="ps-na">비해당</span>` : ""}${stBadge(p.status)}${ubBadge(p.unresolved_by)}</div>
        ${action ? `<div class="ps-action">${linkifyTerms(String(action))}</div>` : ""}
        ${meta.length ? `<div class="ps-meta">${esc(meta.join(" · "))}</div>` : ""}
      </div></div>`;
  }).join("");
  return `<div class="card card-pad ps-card"><div class="rp-sec-h">${I.list} 인허가 절차</div>
    <div class="ps-list">${rows}</div>
    <p class="ps-foot">절차·순서·관할은 법령 근거로 산출된 항목만 표시합니다.</p></div>`;
}

function docCards(card) {
  const docs = orderedDocs(card);
  if (!docs.length) return `<div class="card card-pad"><div class="docs-head"><span style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:700;color:var(--fg-3)">${I.list} 제출 서류</span></div><p style="font-size:14px;color:var(--fg-3);margin:6px 0 0">서류 단계가 산출되지 않았어요. 관할 기관(해당 시·군·구청 건축과)에 직접 문의가 필요해요.</p></div>`;
  const uijaeKeys = new Set(arr(card.uijae).map((u) => u && u.stage_key).filter(Boolean));
  // item 17: 모든 제출서류를 동등 카드로 렌더(의제를 주 단계 하위에 강제삽입하지 않음). 의제 stage는 '관련 인허가' chip만 표시.
  let n = 0;
  return docs.map((d) => docStageCard(d, ++n, uijaeKeys.has(String(d.stage || d.stage_key || "")))).join("");
}

function docStageCard(d, num, isUijae) {
  const stage = d.stage || d.stage_key || "단계";
  const ok = (d.list_status || d.status) === "전수확보";   // item 5: 목록확보 = list_status(해당여부는 items[].applies_status와 분리)
  const law = d.law || "", article = d.article || "";
  // item_type 기반 렌더(application/group/doc/spec/cross_ref) — renderDocItems 공용. 신청서 양식도 제출목록 동등 row(메인/부속 구분 제거).
  const R = renderDocItems(_stageItems(d), law, article);
  const orderedHtml = R.html;
  const submit = R.submit, check = R.check, off = R.off, xref = R.xref;

  // item 17: 의제 하위삽입·§11⑤ 하드코딩 제거 — 의제도 동등 카드(아래 chip). 제출처 포털도 코드가 stage 키워드로 확정 안 함(backend 값 없으면 중립 안내).
  const lawLink = law ? `<a class="ds-link" href="${esc(lawURL(law))}" target="_blank" rel="noreferrer">${I.ext} 시행규칙 원문</a>` : "";
  const submitLink = `<span class="ds-link ds-link-note">${I.pin} 제출처는 관할 기관·해당 인허가 시스템에서 확인</span>`;

  // 부제: 제출 N · 확인필요 M · 해당없음 K — 에이전트 판정 반영
  const lawLine = [law, article].filter(Boolean).join(" ");
  const sub = ok
    ? `${esc(lawLine)}${lawLine ? " · " : ""}제출 ${submit.length}건${check.length ? ` · 확인필요 ${check.length}건` : ""}${off.length ? ` · 해당없음 ${off.length}건` : ""}${xref.length ? ` · 의제연계 ${xref.length}건` : ""}`
    : `${esc(lawLine || "시행규칙")} · 자동 조회 안 됨`;

  // 시점·의미: 에이전트 생성 한 줄(when_note) 우선, 없으면 본법 조문제목 — hover시 본법 원문 인용(when_quote)
  const wMain = String(d.when_note || d.when_title || "").trim();
  const wLaw = String(d.when_law || "").trim();
  const wQuote = String(d.when_quote || "").trim();
  let whenHtml = "";
  if (wMain) {
    const wsrc = (wLaw && wQuote)
      ? `<span class="ds-when-src" tabindex="0">${esc(wLaw)} 원문<span class="ds-pop">${esc(wQuote)}</span></span>`
      : (wLaw ? `<span class="ds-when-law">${esc(wLaw)}</span>` : "");
    whenHtml = `<div class="ds-when"><span class="ds-when-lbl">언제</span><span class="ds-when-t">${esc(wMain)}</span>${wsrc}</div>`;
  } else if (isUijae) {
    whenHtml = `<div class="ds-when ds-when-u"><span class="ds-when-lbl">언제</span><span class="ds-when-t">관련 인허가(의제로 함께 검토될 수 있음)</span></div>`;
  }

  // 작성주체: 에이전트가 법령근거(신청인/건축사§23/감리자§25)로 생성한 한 줄
  const anote = String(d.author_note || "").trim();
  const authorHtml = anote ? `<div class="ds-author"><span class="ds-author-lbl">작성</span><span class="ds-author-t">${esc(anote)}</span></div>` : "";

  return `<div class="doc-stage ${ok ? "" : "na"}">
    <div class="ds-head">
      <div class="ds-num${isUijae ? " ds-num-u" : ""}">${num}</div>
      <div class="ds-main"><div class="ds-t">${esc(stage)}${isUijae ? `<span class="ds-uijae-chip" title="관련 인허가(의제로 함께 검토)">관련 인허가</span>` : ""}</div><div class="ds-law">${sub}</div></div>
      <span class="ds-badge ${ok ? "ok" : "na"}">${ok ? "법정 제출목록" : "확인필요"}</span>
    </div>
    ${whenHtml}
    ${authorHtml}
    ${ok && orderedHtml ? `<div class="ds-items">${orderedHtml}</div>` : ""}
    ${!ok ? `<div class="ds-na-note">${I.bang}<span>이 단계 서류는 자동 조회가 되지 않았어요. 관할 기관(해당 시·군·구청 건축과 등)에서 직접 확인하세요. <b>서류가 없다는 뜻은 아니에요.</b></span></div>` : ""}
    <div class="ds-links">${lawLink}${submitLink}</div>
  </div>`;
}

// ============================================================
//  자유 입력 (간단 — 주소기준 추가질문은 정적 안내 or 재진단)
// ============================================================
async function freeReply(text) {
  const c = S.active;
  // HITL 대기 중이면 — 자유텍스트 답을 resume로(에이전트 LLM이 면적·층수 등 해석). 중단어면 reject.
  if (c._hitl) {                                  // submit이 이미 pushUser함 → 여기선 중복 push 안 함
    const tid = c._hitl.thread_id, oldThink = c._hitl.think; c._hitl = null;
    if (oldThink && oldThink.done) oldThink.done(c);   // 직전 검토버블은 '검토 완료' 칩으로 접고, 새 검토버블이 사용자 답 '아래'에 뜨게(사고보기 위로 안 감 — 사용자 요구)
    const stop = /^\s*(중단|취소|그만|중지|stop)\s*$/i.test(text);
    const qs = new URLSearchParams({ thread_id: tid });
    if (stop) qs.set("reject", "true"); else qs.set("answer", text);
    resumeStream("/diagnose/resume?" + qs.toString());   // think 안 넘김 → makeThinking이 하단(사용자 답 아래)에 새 버블 + scrollBottom
    return;
  }
  // 재진단 명령(이미 용도 있을 때) → 같은 용도로 다시
  if (c.use_type && /다시|재진단|새로|재검토|다시\s*해/.test(text)) { rediagnose(); return; }
  // 결과 후 '(다른) X 지을 수 있을까/지어도 되나' = 새 용도 진단(기존 trace·결과 비우고 처음부터, 용도는 에이전트가 텍스트서 해석).
  //  followup으로 가면 옛 사고과정 남고 카드가 옛 용도 서류+새 verdict로 섞임 → 새 진단으로 분리.
  if (c.threadId && c.result && /지을\s*수\s*있|지어도\s*(되|괜찮)|세울\s*수\s*있|올려도\s*(되|괜찮)|건축\s*가능|짓고\s*싶|지어도\s*돼/.test(text)) {
    chooseUse(text, text, true); return;
  }
  // 진단 완료 후 입력 = 후속질문 → 같은 thread로(에이전트가 컨텍스트 갖고 답). 새 진단 아님
  if (c.threadId && c.result) {
    runDiagnoseStream("/diagnose/followup?" + new URLSearchParams({ thread_id: c.threadId, message: text }).toString(), true);
    return;
  }
  // 첫 진단 — 그 텍스트를 용도로(건축법 용도 해석은 에이전트가 ReAct)
  chooseUse(text, text, true);
}

// 같은 주소·use_type·규모로 /diagnose/stream 재실행(실제 재진단)
async function rediagnose() {
  const c = S.active;
  if (!c) return;
  if (!c.use_type) { await aiSay("어떤 건축 행위로 다시 진단할지 먼저 알려주세요.", 400); pushAINode(quickActions()); return; }
  closePanel();
  await aiSay(`<b>${esc(c.loc.address)}</b> 기준으로 다시 진단할게요.`, 400);
  setStage(2);
  const params = { address: c.loc.address, use_type: c.use_type };   // 위 1186서 use_type 보장 — 디폴트 날조 안 함(무하드코딩)
  // 면적·층수 강제 안 함 — 이전 진단서 확정됐으면 재사용, 없으면 에이전트가 다시 물음
  if (c.floor_area != null) params.floor_area = String(c.floor_area);
  if (c.floor_count != null) params.floor_count = String(c.floor_count);
  runDiagnoseStream("/diagnose/stream?" + new URLSearchParams(params).toString());
}

// ============================================================
//  dynamic wiring
// ============================================================
function wireDynamic() {
  $$(".qa[data-use]").forEach((b) => { if (b._w) return; b._w = 1; b.onclick = () => { if (b.dataset.use) chooseUse(b.dataset.use, b.dataset.name); else { aiSay("어떤 시설을 짓고 싶은지 적어 주세요. (예: 수영장, 학원, 미용실)", 300); const ta = $("#cmpInput"); if (ta) ta.focus(); } }; });
  $$('[data-act="openpanel"]').forEach((b) => { if (b._w) return; b._w = 1; b.onclick = () => { if (S.active) { renderPanel(S.active); openPanel(); } }; });
  $$('[data-act="toggle-detail"]').forEach((b) => { if (b._w) return; b._w = 1; b.onclick = () => { const d = b.parentElement && b.parentElement.querySelector(".am-detail"); if (d) { d.hidden = !d.hidden; b.classList.toggle("open", !d.hidden); } }; });
  $$('[data-act="retry"]').forEach((b) => { if (b._w) return; b._w = 1; b.onclick = () => rediagnose(); });   // LLM 실패 '다시 진단'
  wireTerms();
}

// ============================================================
//  용어 popover
// ============================================================
let pop = null;
function wireTerms() {
  $$(".term").forEach((t) => { if (t._w) return; t._w = 1; t.onmouseenter = () => showPop(t); t.onmouseleave = hidePop; t.onclick = (e) => { e.stopPropagation(); showPop(t); }; t.tabIndex = 0; t.onfocus = () => showPop(t); t.onblur = hidePop; });
}
function showPop(t) {
  hidePop(); const g = GLOSSARY[t.dataset.term]; if (!g) return;
  // 진단맥락 용어설명(에이전트 생성) — 정적 정의 아래 '이 진단에선' 단락. 없으면 정적 정의만.
  const tn = (S.active && S.active.result && S.active.result._return && S.active.result._return.card && S.active.result._return.card.term_notes) || {};
  const note = tn[t.dataset.term];
  pop = el("div", "term-pop", `<div class="tp-t">${esc(g[0])}</div>${esc(g[1])}${note ? `<div class="tp-ctx">이 진단에선 — ${esc(String(note))}</div>` : ""}`);
  document.body.appendChild(pop);
  const r = t.getBoundingClientRect();
  let top = r.bottom + 8, left = Math.min(r.left, window.innerWidth - 316);
  if (left < 12) left = 12;
  if (top + pop.offsetHeight > window.innerHeight - 12) top = r.top - pop.offsetHeight - 8;
  pop.style.top = top + "px"; pop.style.left = left + "px";
  requestAnimationFrame(() => pop && pop.classList.add("show"));
}
function hidePop() { if (pop) { pop.remove(); pop = null; } }
document.addEventListener("click", hidePop);
document.addEventListener("scroll", hidePop, true);

// ============================================================
//  composer
// ============================================================
function wireComposer() {
  const ta = $("#cmpInput"), send = $("#cmpSend");
  const upd = () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 120) + "px"; send.disabled = ta.value.trim() === ""; };
  ta.addEventListener("input", upd);
  ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } });
  send.addEventListener("click", submit);
  function submit() {
    const v = ta.value.trim(); if (!v || !S.active) return;
    if (S.active._streaming && !S.active._hitl) return;   // 진행 중(비-HITL)엔 새 진단 시작 막음 — 중복제출이 컨텍스트 날리는 버그 방지
    ta.value = ""; upd(); pushUser(v); freeReply(v);
  }
  upd();
}

// ── 모바일 드로어 ──
function openDrawer() { $(".sidebar").classList.add("open"); $("#scrim").classList.add("show"); }
function closeDrawer() { $(".sidebar").classList.remove("open"); $("#scrim").classList.remove("show"); }

// ============================================================
//  카카오 SDK 동적 로드 (/config 키 — 하드코딩 금지)
// ============================================================
async function loadKakaoSDK() {
  try {
    const r = await fetch("/config");
    const j = await r.json();
    if (!j || !j.kakao_js_key) return;
    S.kakaoKey = j.kakao_js_key;
    await new Promise((res) => {
      const s = document.createElement("script");
      s.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${j.kakao_js_key}&libraries=services&autoload=false`;
      s.onload = () => res();
      s.onerror = () => res(); // 실패해도 폴백 지도로 진행
      document.head.appendChild(s);
    });
  } catch (e) { /* config 없으면 맵 생략 → 폴백 */ }
}

// ============================================================
//  init
// ============================================================
async function init() {
  if (init._done) return; init._done = true;
  restore();
  $("#newChat").onclick = () => { closeDrawer(); openMap(); };
  $("#overlay").addEventListener("click", (e) => { if (e.target.id === "overlay") closeMap(); });
  $("#changeAddr") && ($("#changeAddr").onclick = openMap);
  $("#menuBtn") && ($("#menuBtn").onclick = openDrawer);
  $("#scrim") && ($("#scrim").onclick = closeDrawer);
  $("#mbarChange") && ($("#mbarChange").onclick = openMap);
  window.__closeDrawer = closeDrawer;
  // 결과 패널 닫기/백드롭/재오픈 와이어링
  $("#rpClose") && ($("#rpClose").onclick = closePanel);
  $("#rpBackdrop") && ($("#rpBackdrop").onclick = closePanel);
  $("#rpClose") && ($("#rpClose").innerHTML = I.x);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePanel(); });
  renderRail();
  wireComposer();
  showOnboard();
  await loadKakaoSDK(); // 온보딩 후 백그라운드 로드 — 지도 모달 열기 전 준비
}

document.addEventListener("DOMContentLoaded", init);
if (document.readyState !== "loading") init();
