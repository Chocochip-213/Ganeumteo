# -*- coding: utf-8 -*-
"""노드/도구 → 사용자 표시 한글 라벨. 모르는 노드/도구는 generic(단일 케이스 분기 금지 — 과적합 방지)."""

NODE_LABELS = {
    "agent": "다음 행동 판단",
    "tools": "도구 실행",
    "completeness_guard": "누락 점검",
    "build_reasoning": "논증 구성",
    "compose": "진단 리포트 조립",
    "finalize": "종료 정리",
    "abstain": "판단 보류",
}

TOOL_LABELS = {
    "geocode": "주소 → 좌표",
    "get_parcel": "필지 조회(지목·도로접면)",
    "get_land_use": "용도지역·규제 중첩",
    "get_land_price": "공시지가",
    "act_landuse": "행위제한 1차 판정",
    "ordin_byeolpyo_fetch": "조례 별표 본문",
    "law_byeolpyo_fetch": "건축법령 별표 대조",
    "law_article_fetch": "법령 조문 조회",
    "docs_for_stage": "단계별 제출서류",
    "compute_scale": "규모 상한",
    "compute_envelope": "건폐율·용적률 규모",
    "parking_quota": "부설주차 산정",
    "levy_estimate": "부담금 추정",
    "author_rule_tool": "작성주체(건축사)",
    "reg_effect_resolve_tool": "규제별 근거 법령",
    "record_uijae": "의제(인허가 의제) 기록",
    "record_ordinance_ruling": "조례 호목 해소",
    "request_human_input": "사용자 확인 요청",
}


def node_label(node):
    return NODE_LABELS.get(node, "단계 진행 중")


def tool_label(tool):
    return TOOL_LABELS.get(tool, tool)


def done_label(node, delta):
    """노드 완료 한 줄. delta(노드 반환 dict)에서 가벼운 단서만."""
    base = NODE_LABELS.get(node, node)
    if node == "completeness_guard":
        return base + (" — 미충족 보완 요청" if delta.get("_incomplete") else " — 통과")
    return base + " 완료"
