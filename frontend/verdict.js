// 판정 분류 — #1 과적합 가드. 백엔드 verdict는 "오픈 문자열"(가능/가능(조건부)/위험·금지/확인필요 + 미지의 값).
// enum switch 금지: prefix/substring으로 톤만 정하고, 모르는 값은 raw로 그대로 렌더(크래시·공백 금지).
export function classifyVerdict(s) {
  const v = (s == null ? "" : String(s)).trim();
  if (!v) return { tone: "neutral", label: "확인필요", raw: false };
  if (v.startsWith("가능") && v.includes("조건부")) return { tone: "conditional", label: v };
  if (v === "가능" || (v.startsWith("가능") && !v.includes("조건부"))) return { tone: "affirmative", label: v };
  if (v.includes("위험") || v.includes("금지") || v === "불가") return { tone: "danger", label: v }; // '위험·금지' 한 칩, 가운뎃점 보존
  if (v.includes("확인필요") || v.includes("확인 필요")) return { tone: "neutral", label: v };
  return { tone: "neutral", label: v, raw: true }; // 미지의 값 → 그대로 표시
}

export const TONE_KO = {
  affirmative: "건축 가능",
  conditional: "조건부 가능",
  danger: "위험·금지",
  neutral: "확인 필요",
};

// terminal_reason → 사용자 상태 라벨(7값 + unknown→완료)
export const STATUS_KO = {
  completed: "완료", verdict_resolved: "조기종료", need_human: "사람검토",
  step_capped: "부분완료(단계 한도)", no_grounds: "근거 부족(확인필요)", context_overflow: "재시도필요(컨텍스트 초과)",
  record_loop: "확인필요(판정 근거 반복 미확보)", tool_budget_exhausted: "부분완료(추가 조사 한도 — 미해결 잔존)",
  site_geocode_failed: "재입력필요", fallback_extract_failed: "부분완료",
  error: "부분완료", aborted: "중단", llm_error: "재시도필요",
};
export function statusKo(tr) { return STATUS_KO[tr] || "부분완료(확인 권장)"; }   // 미매핑 종료사유를 '완료'로 위장하지 않음(검수 A2)
