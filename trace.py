# -*- coding: utf-8 -*-
"""실행 트레이스 — agent의 도구선택·결과를 실시간 출력 + 로그파일(trace_last.log). 명세 부록 F.
GMS 주의: astream_events는 tool_call_id 충돌 → stream_mode='updates' 사용(검증됨, 네 노트 #9).
사용: uv run python trace.py "<주소>"        (실 LLM, GMS)
      uv run python trace.py "<주소>" stub    (결정적 stub, 빠름)"""
import sys, os
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from graph import build_graph

LOG = []
def emit(line):
    print(line, flush=True)
    LOG.append(line)

def _short(d, n=70):
    s = ", ".join(f"{k}={str(v)[:24]}" for k, v in (d or {}).items())
    return s[:n] + ("…" if len(s) > n else "")

def trace(address, use="카페(일반음식점)", area=264.0, floors=1):
    g, mode = build_graph()
    emit(f"━━━ 실행 트레이스 / agent={mode} ━━━")
    emit(f"입력: {address} / 용도={use} / 연면적={area}㎡ {floors}층 신축\n")
    msg = HumanMessage(f"주소 {address}. 용도={use}, 연면적 {area}㎡, {floors}층, 신축. "
                       f"이 땅 건축 인허가 사전진단을 수행하라. geocode부터 시작.")
    st = {"messages": [msg], "address": address, "use_type": use, "floor_area": area, "floor_count": floors,
          "work_type": "신축", "reg_overlaps": [], "uijae": [], "documents": [], "reg_effects": [],
          "jorye_verdicts": [], "citations": [], "abstentions": [], "_toolcalls": [], "_steps": 0}
    step = 0
    import uuid
    cfg = {"recursion_limit": 80, "configurable": {"thread_id": "tr-" + uuid.uuid4().hex[:8]}}
    for chunk in g.stream(st, cfg, stream_mode="updates"):
        for node, delta in chunk.items():
            step += 1
            msgs = (delta or {}).get("messages", []) if isinstance(delta, dict) else []
            if node == "agent":
                for m in msgs:
                    if isinstance(m, AIMessage):
                        if m.tool_calls:
                            for tc in m.tool_calls:
                                emit(f"[{step:02d}] 🧠 agent 판단 → 도구호출: {tc['name']}({_short(tc.get('args'))})")
                        elif (m.content or "").strip():
                            emit(f"[{step:02d}] 🧠 agent: {str(m.content)[:90]}")
            elif node == "tools":
                for m in msgs:
                    if isinstance(m, ToolMessage):
                        emit(f"[{step:02d}] 🔧 도구결과: {str(m.content)[:130].replace(chr(10), ' ')}")
            elif node == "completeness_guard":
                emit(f"[{step:02d}] ✅ 완결성가드: {'미흡→재조사' if (delta or {}).get('_incomplete') else '충분→판정'}")
            elif node == "build_reasoning":
                lr = (delta or {}).get("legal_reasoning", {})
                emit(f"[{step:02d}] 🧩 논증골격: {len(lr.get('steps', []))}단계 / verdict={delta.get('verdict')}")
            elif node == "compose":
                emit(f"[{step:02d}] 📝 카드조립 완료")
            elif node in ("finalize", "abstain"):
                emit(f"[{step:02d}] 🏁 {node}: terminal={delta.get('terminal_reason')}")
    emit("\n━━━ 트레이스 끝 ━━━")

if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    if "stub" in args:
        os.environ["FORCE_STUB"] = "1"; args = [a for a in args if a != "stub"]
    addr = args[0] if args else "경기도 양평군 용문면 다문리 100"
    try:
        trace(addr)
    finally:
        with open("trace_last.log", "w", encoding="utf-8") as f:
            f.write("\n".join(LOG))
        print("\n>>> 로그 저장: trace_last.log")
