# -*- coding: utf-8 -*-
"""graph.stream(stream_mode='updates') → 정규화 TraceEvent SSE 스트림.
- 동기 제너레이터: Starlette StreamingResponse가 threadpool에서 iterate → 이벤트루프 비차단(검수 HIGH).
- astream_events 금지(GMS gpt-5.2서 tool_call_id=None ValidationError) — updates 경로만.
- found = 확장 실패토큰셋(검수 fix#7: 못찾음·없음·빈값 포함). _safe_*로 원문 누출 차단(quote≤110)."""
import json
from langgraph.types import Command
from labels import tool_label, done_label

FAIL_TOKENS = ("실패", "미확보", "못찾음", "없음", "빈값", "조회 실패", "추출 실패", "미확정", "확인필요", "오류")


def _q(s, n=110):
    return str(s or "")[:n]


def _safe_args(args):
    if not isinstance(args, dict):
        return {}
    out = {}
    for k, v in args.items():
        if isinstance(v, str):
            out[k] = v[:120]
        elif isinstance(v, (int, float, bool)):
            out[k] = v
        elif isinstance(v, list):
            out[k] = [str(x)[:60] for x in v[:6]]
        else:
            out[k] = str(v)[:120]
    return out


def _safe_cite(c):
    c = c if isinstance(c, dict) else {}
    return {"source": c.get("source"), "law_name": c.get("law_name"), "article": c.get("article"),
            "title": c.get("title"), "quote": _q(c.get("quote"), 110),
            "url": c.get("url"), "extract_method": c.get("extract_method")}


def _msg_attr(m, attr, default=None):
    return m.get(attr, default) if isinstance(m, dict) else getattr(m, attr, default)


def _events(graph, state, cfg, resume=None):
    seq = 0

    def ev(kind, node=None, label="", detail=None):
        nonlocal seq
        seq += 1
        return {"seq": seq, "ts_seq": seq, "kind": kind, "node": node, "label": label, "detail": detail}

    stream_in = Command(resume=resume) if resume is not None else state
    for chunk in graph.stream(stream_in, cfg, stream_mode="updates"):
        for node, delta in (chunk or {}).items():
            if not isinstance(delta, dict):
                continue
            if node == "agent":
                msgs = delta.get("messages") or []
                last = msgs[-1] if msgs else None
                tcs = _msg_attr(last, "tool_calls") if last is not None else None
                if tcs:
                    for tc in tcs:                                  # 병렬 호출 = 같은 agent 턴(seq는 각자 +1, dedup은 프론트)
                        name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                        args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                        yield ev("tool_call", node, tool_label(name), {"tool": name, "args": _safe_args(args)})
                else:
                    content = _msg_attr(last, "content", "") if last is not None else ""
                    if content:
                        yield ev("thinking", node, "🤖 판단", {"text": _q(content, 300)})
            elif node == "tools":
                for m in (delta.get("messages") or []):
                    c = _msg_attr(m, "content", "")
                    name = _msg_attr(m, "name")
                    found = not any(t in str(c) for t in FAIL_TOKENS)
                    yield ev("tool_result", node, (tool_label(name) if name else "🔧 결과"),
                             {"tool": name, "found": found, "quote": _q(c, 160)})
                for cit in (delta.get("citations") or []):
                    yield ev("citation", node, "🔖 근거 확보", _safe_cite(cit))
                if "doc_index_hit" in delta:
                    yield ev("node_done", node,
                             ("📖 조례 인덱스 HIT" if delta["doc_index_hit"] else "📖 조례 라이브 조회"), None)
            elif node == "completeness_guard":
                yield ev("node_done", node, done_label(node, delta), {"incomplete": bool(delta.get("_incomplete"))})
            elif node == "build_reasoning":
                lr = delta.get("legal_reasoning") or {}
                yield ev("verdict", node, "🧩 1차 판정 도출",
                         {"verdict": delta.get("verdict"), "steps": len(lr.get("steps", [])),
                          "basis_seq": lr.get("verdict_basis_seq", [])})
            elif node == "compose":
                yield ev("node_done", node, "📋 진단 리포트 조립 완료", None)
            elif node == "finalize":
                yield ev("done", node, "🏁 진단 완료", {"terminal_reason": delta.get("terminal_reason")})
            elif node == "abstain":
                yield ev("abstain", node, "⏸ 자동판정 보류", {"terminal_reason": delta.get("terminal_reason")})

    snap = graph.get_state(cfg)                                    # interrupt(HITL) 감지
    if snap.next:
        intr = None
        try:
            intr = snap.tasks[0].interrupts[0].value
        except Exception:
            intr = {"type": "need_input"}
        yield ev("interrupt", None, "✋ 사용자 입력 필요", intr)


def run_stream(graph, state, cfg, resume=None):
    """SSE 프레임(text/event-stream) 동기 제너레이터."""
    try:
        for e in _events(graph, state, cfg, resume=resume):
            yield "data: " + json.dumps(e, ensure_ascii=False) + "\n\n"
    except Exception as ex:
        for e in ({"seq": 9998, "ts_seq": 9998, "kind": "error", "node": None,
                   "label": "⚠️ 조회 오류", "detail": {"error": type(ex).__name__}},
                  {"seq": 9999, "ts_seq": 9999, "kind": "done", "node": None,
                   "label": "🏁 종료", "detail": {"terminal_reason": "error"}}):
            yield "data: " + json.dumps(e, ensure_ascii=False) + "\n\n"
