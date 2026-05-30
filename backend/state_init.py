# -*- coding: utf-8 -*-
"""사용자 입력 → 초기 GaneomteoState + 실행 config. 서버가 thread_id 생성(검수 fix#11)."""
import uuid
from langchain_core.messages import HumanMessage


def fresh_state(address, use_type, floor_area, floor_count):
    msg = HumanMessage(
        f"주소 {address}. 용도={use_type}, 연면적 {floor_area}㎡, {floor_count}층, 신축. "
        f"geocode부터 시작해 입지·행위제한·조례·서류·규모·작성주체를 조사하라.")
    return {
        "messages": [msg],
        "address": address, "use_type": use_type,
        "floor_area": float(floor_area), "floor_count": int(floor_count), "work_type": "신축",
        # operator.add 누적 필드 전부 pre-init(미초기화 시 누적 오류 — 검수 검증)
        "reg_overlaps": [], "uijae": [], "documents": [], "reg_effects": [], "jorye_verdicts": [],
        "citations": [], "abstentions": [], "_toolcalls": [], "_steps": 0,
    }


def make_config(thread_id=None):
    """서버 생성 thread_id(클라가 안 주면). recursion_limit=80(run.py/trace.py 동일)."""
    tid = thread_id or ("req-" + uuid.uuid4().hex[:8])
    return tid, {"recursion_limit": 80, "configurable": {"thread_id": tid}}
