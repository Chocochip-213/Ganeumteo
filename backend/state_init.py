# -*- coding: utf-8 -*-
"""사용자 입력 → 초기 GaneomteoState + 실행 config. 서버가 thread_id 생성(검수 fix#11)."""
import uuid
from langchain_core.messages import HumanMessage


def fresh_state(address, use_type, floor_area=None, floor_count=None):
    scale_txt = f"연면적 {floor_area}㎡, {floor_count}층. " if floor_area is not None else ""
    use_txt = f"용도='{use_type}'. " if use_type else "용도 미정(사용자가 아직 안 밝힘 — 코드가 디폴트 가정 안 함, 무엇을 하려는지 되물어라). "
    msg = HumanMessage(
        f"주소 {address}. {use_txt}{scale_txt}"
        f"이게 건축물·용도·인허가 문의면 geocode부터 진단(입지·행위제한·조례·서류·규모·작성주체)을 진행하라. "
        f"신축인지·기존 건물 용도변경인지·대수선/증축/철거인지는 사용자 말에서 네가 판단하라(코드가 신축으로 가정하지 않음). 모호하면 되물어라. "
        f"단순 인사·잡담·건축과 무관한 말이면 도구를 부르지 말고 평이하게 무엇을 어디에 어떻게(신축/용도변경 등) 하려는지 되물어라.")
    return {
        "messages": [msg],
        "address": address, "use_type": use_type,
        "floor_area": float(floor_area) if floor_area is not None else None,
        "floor_count": int(floor_count) if floor_count is not None else None, "work_type": "",
        # operator.add 누적 필드 전부 pre-init(미초기화 시 누적 오류 — 검수 검증)
        "reg_overlaps": [], "uijae": [], "documents": [], "cond_assessments": [], "reg_effects": [], "jorye_verdicts": [], "verdict_labels": [], "document_facts": {},
        "citations": [], "abstentions": [], "_toolcalls": [], "_steps": 0,
        "_turn_base_steps": 0, "_turn_base_tools": 0,   # per-invoke 하드캡 기준(검수 AF-1/2/3)
    }


def make_config(thread_id=None):
    """서버 생성 thread_id(클라가 안 주면). recursion_limit=80(run.py/trace.py 동일)."""
    tid = thread_id or ("req-" + uuid.uuid4().hex[:8])
    return tid, {"recursion_limit": 80, "configurable": {"thread_id": tid}}
