# -*- coding: utf-8 -*-
"""graph.stream(stream_mode='updates') → 정규화 TraceEvent SSE 스트림.
- 동기 제너레이터: Starlette StreamingResponse가 threadpool에서 iterate → 이벤트루프 비차단(검수 HIGH).
- astream_events 금지(GMS gpt-5.2서 tool_call_id=None ValidationError) — updates 경로만.
- found = 도구턴이 emit한 구조신호(abstentions/jorye_verdicts 확인필요/terminal 실패)로 도출 — 문자열 스니핑 금지(검수 fix#7). _safe_*로 원문 누출 차단(quote≤110)."""
import json
from langgraph.types import Command
from labels import tool_label, done_label


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


def _text_content(content):
    """Responses API(gpt-5.2-pro)면 content가 list(text/function_call/reasoning 파트) — 텍스트만 추출.
    Chat Completions면 str 그대로. 함수콜 dict가 '사고' 텍스트로 새는 것 차단."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and p.get("type") in ("text", "output_text") and p.get("text"):
                parts.append(str(p["text"]))
        return " ".join(parts).strip()
    return ""


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
                content = _text_content(_msg_attr(last, "content", "")) if last is not None else ""
                tcs = _msg_attr(last, "tool_calls") if last is not None else None
                # 사고(content)를 도구호출 앞에 먼저 노출(GPT/Claude Thinking식) — content와 tool_calls 둘 다
                if content and str(content).strip():
                    yield ev("thinking", node, "판단", {"text": _q(content, 400)})
                if tcs:
                    for tc in tcs:                                  # 병렬 호출 = 같은 agent 턴(seq는 각자 +1, dedup은 프론트)
                        name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                        args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                        yield ev("tool_call", node, tool_label(name), {"tool": name, "args": _safe_args(args)})
            elif node == "tools":
                # found = 이 도구턴의 구조신호로 판정(문자열 스니핑 X): 기권 추가됐나 / 조례판정이 확인필요인가 /
                #  종료사유가 실패형인가. 정상 부정판정('관련 규제 없음')·정당한 위임결과는 실패로 오표시하지 않음.
                abst = delta.get("abstentions") or []
                jvs = delta.get("jorye_verdicts") or []
                tr = delta.get("terminal_reason")
                unsure = bool(abst) or any(
                    (jv.get("verdict") == "확인필요") for jv in jvs if isinstance(jv, dict)) \
                    or tr in ("site_geocode_failed", "error", "aborted", "fallback_extract_failed")
                found = not unsure
                for m in (delta.get("messages") or []):
                    c = _msg_attr(m, "content", "")
                    name = _msg_attr(m, "name")
                    yield ev("tool_result", node, (tool_label(name) if name else "결과"),
                             {"tool": name, "found": found, "quote": _q(c, 160)})
                for cit in (delta.get("citations") or []):
                    yield ev("citation", node, "근거 확보", _safe_cite(cit))
                if "doc_index_hit" in delta:
                    yield ev("node_done", node,
                             ("조례 인덱스 적중" if delta["doc_index_hit"] else "조례 라이브 조회"), None)
            elif node == "completeness_guard":
                yield ev("node_done", node, done_label(node, delta), {"incomplete": bool(delta.get("_incomplete"))})
            elif node == "build_reasoning":
                lr = delta.get("legal_reasoning") or {}
                yield ev("verdict", node, "1차 판정 도출",
                         {"verdict": delta.get("verdict"), "steps": len(lr.get("steps", [])),
                          "basis_seq": lr.get("verdict_basis_seq", [])})
            elif node == "compose":
                yield ev("node_done", node, "진단 리포트 조립 완료", None)
            elif node == "finalize":
                yield ev("done", node, "진단 완료", {"terminal_reason": delta.get("terminal_reason")})
            elif node == "abstain":
                yield ev("abstain", node, "자동판정 보류", {"terminal_reason": delta.get("terminal_reason")})

    snap = graph.get_state(cfg)                                    # interrupt(HITL) 감지
    if snap.next:
        intr = None
        try:
            intr = snap.tasks[0].interrupts[0].value
        except Exception:
            intr = {"type": "need_input"}
        yield ev("interrupt", None, "사용자 입력 필요", intr)


def run_stream(graph, state, cfg, resume=None):
    """SSE 프레임(text/event-stream) 동기 제너레이터."""
    try:
        for e in _events(graph, state, cfg, resume=resume):
            yield "data: " + json.dumps(e, ensure_ascii=False) + "\n\n"
    except Exception as ex:
        for e in ({"seq": 9998, "ts_seq": 9998, "kind": "error", "node": None,
                   "label": "조회 오류", "detail": {"error": type(ex).__name__}},
                  {"seq": 9999, "ts_seq": 9999, "kind": "done", "node": None,
                   "label": "종료", "detail": {"terminal_reason": "error"}}):
            yield "data: " + json.dumps(e, ensure_ascii=False) + "\n\n"
