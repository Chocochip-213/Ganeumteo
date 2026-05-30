// 실시간 실행 트레이스. 모든 SSE kind 처리 + 모르는 kind는 무시(과적합 방지: 단일 케이스 분기 없음).
// 병렬 tool_call은 (tool,args)로 dedup(같은 seq 공유). 순서는 도착순(서버 seq).
let _el = null, _seen = new Set();

export function resetTrace(el) { _el = el; _seen = new Set(); el.innerHTML = ""; }

function trunc(s, n = 60) { s = (s == null ? "" : String(s)); return s.length > n ? s.slice(0, n) + "…" : s; }

function line(extraCls, lab, meta) {
  const d = document.createElement("div");
  d.className = "tline " + extraCls;
  const b = document.createElement("div"); b.className = "body";
  const l = document.createElement("div"); l.className = "lab"; l.textContent = lab; b.appendChild(l);
  if (meta) { const m = document.createElement("div"); m.className = "meta"; m.textContent = meta; b.appendChild(m); }
  const t = document.createElement("div"); t.className = "tick";
  d.appendChild(t); d.appendChild(b);
  _el.appendChild(d); _el.scrollTop = _el.scrollHeight;
  return d;
}

export function appendTrace(ev) {
  if (!_el || !ev || !ev.kind) return;
  switch (ev.kind) {
    case "meta":
      line("node", "📋 접수: " + (ev.detail?.address || ""), ev.detail?.use_type || ""); break;
    case "tool_call": {
      const key = (ev.detail?.tool || "") + JSON.stringify(ev.detail?.args || {});
      if (_seen.has(key)) return;                 // dedup
      _seen.add(key);
      const args = ev.detail?.args ? Object.entries(ev.detail.args).map(([a, b]) => `${a}=${trunc(b, 30)}`).join("  ") : "";
      line("tool", ev.label || ev.detail?.tool, args); break;
    }
    case "tool_result":
      line(ev.detail?.found === false ? "warn" : "muted",
           (ev.detail?.found === false ? "⚠ " : "") + (ev.label || "결과"), trunc(ev.detail?.quote)); break;
    case "citation":
      line("cite", "🔖 " + [ev.detail?.law_name, ev.detail?.article].filter(Boolean).join(" "),
           trunc(ev.detail?.quote, 50)); break;
    case "verdict":
      line("node", "🧩 1차 판정: " + (ev.detail?.verdict ?? "?"),
           `근거단계 ${(ev.detail?.basis_seq || []).length} / 전체 ${ev.detail?.steps ?? "?"}`); break;
    case "node_done":
      line("node muted", ev.label || "", ""); break;
    case "thinking":
      line("muted", "🤖 " + trunc(ev.detail?.text, 90), ""); break;
    case "abstain":
      line("warn", ev.label || "보류", ev.detail?.terminal_reason || ""); break;
    case "error":
      line("warn", ev.label || "오류", ev.detail?.error || ""); break;
    case "done":
      line("node", ev.label || "완료", ev.detail?.terminal_reason || ""); break;
    case "interrupt":
      break;   // app.js가 입력 폼으로 처리
    default:
      break;   // 모르는 kind → 무시(절대 크래시 안 함)
  }
}
