# -*- coding: utf-8 -*-
"""agent 노드 — LLM 키 있으면 ChatAnthropic(진짜 ReAct), 없으면 결정적 stub-planner.
stub은 실제 tool_calls를 발행 → LangGraph ToolNode+Command 브리지를 진짜로 구동(지능만 스크립트)."""
import os, uuid
from langchain_core.messages import AIMessage
from tools import TOOLS
import wf_docs_agent as DOC

AGENT_SYSTEM = """너는 대한민국 건축 인허가 사전진단 에이전트다. [주소/좌표 + 용도]를 받아 도구로 사실을 수집·판정해 진단 카드를 만든다.
[원칙] 1.사실은 도구 결과로만(기억 금지), 없으면 확인필요 기권. 2.모든 판정·서류·근거에 인용. 3.조례 별표가 "건축법 시행령 별표1 제N호 O목"을 참조하면 law_byeolpyo_fetch로 별표1 가져와 호목 해소(멀티홉). 4.용도 해석(카페→일반음식점=제2종근린생활시설).
[인자 전달] 각 도구의 인자는 이전 도구 결과(ToolMessage)에서 가져와라. 예: get_parcel이 준 PNU를 get_land_use(pnu=...)에 / geocode가 준 x,y를 get_parcel(x=,y=)에 / get_land_use가 준 UQ코드를 act_landuse(zone_ucode=)에 / get_parcel이 준 시군구·get_land_use의 용도지역을 ordin_byeolpyo_fetch(sigungu=,zone=)에.
[권장순서] geocode→get_parcel→get_land_use→get_land_price→act_landuse →(act가 '조례확인필요'면)ordin_byeolpyo_fetch→law_byeolpyo_fetch→record_ordinance_ruling →(지목 전답과수원임야면)record_uijae →docs_for_stage→compute_scale→author_rule_tool→reg_effect_resolve_tool.
[docs_for_stage 호출법] stage_key는 반드시 실제 단계명만: '건축허가','착공신고','사용승인' 3개 + record_uijae로 기록한 의제의 stage_key 각각(농지전용/산지전용/개발행위). '의제단계' 같은 placeholder 문자열 금지. 의제 없으면 건축허가·착공신고·사용승인 3개만.
[중요·종료규칙] 같은 도구를 두 번 부르지 마라(이미 결과 받은 도구 재호출 금지). 위 항목을 다 모았으면 **도구를 부르지 말고** 짧게 '완료'라고만 답하라. 좌표가 이미 주어졌으면 geocode 생략하고 get_parcel부터."""

_DOC_STAGES = set(DOC.DOC_SOURCE.keys())   # docs_for 지원 단계
_UIJAE = {"전": "농지전용", "답": "농지전용", "과수원": "농지전용", "임야": "산지전용", "목장용지": "초지전용"}
_PERMIT = {"전": "농지전용허가", "답": "농지전용허가", "과수원": "농지전용허가", "임야": "산지전용허가", "목장용지": "초지전용허가"}


def _call(name, args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "call_" + uuid.uuid4().hex[:8]}])


def stub_plan(state):
    """결정적 planner: State 보고 다음 도구 1개 발행. LLM 없이 ReAct 그래프 구동(과적합 체크용)."""
    called = set(state.get("_toolcalls", []))
    pnu = state.get("pnu"); zone = state.get("zone")
    # 입지
    if not pnu:
        if state.get("_xy") and "get_parcel" not in called:
            x, y = state["_xy"]; return _call("get_parcel", {"x": x, "y": y})
        if not state.get("_xy") and "geocode" not in called and state.get("address", "").strip():
            return _call("geocode", {"address": state["address"]})
        if state.get("_xy") and "get_parcel" in called:
            pass  # 필지 실패 → 아래 종료
    if pnu and not zone and "get_land_use" not in called:
        return _call("get_land_use", {"pnu": pnu})
    if pnu and "land_price" not in state and "get_land_price" not in called:
        return _call("get_land_price", {"pnu": pnu})
    if zone and "act_verdict" not in state and "act_landuse" not in called:
        uc = (state.get("zone_ucodes") or [""])[0]
        return _call("act_landuse", {"zone_ucode": uc, "use_type": state["use_type"], "area_cd": state.get("area_cd", "")})
    # 조례 멀티홉
    if state.get("_delegated") and "ordin_byeolpyo_fetch" not in called and state.get("sigungu"):
        return _call("ordin_byeolpyo_fetch", {"sigungu": state["sigungu"], "zone": zone})
    if "ordin_byeolpyo_fetch" in called and "law_byeolpyo_fetch" not in called:
        return _call("law_byeolpyo_fetch", {"law_name": "건축법 시행령", "byeolpyo_kw": "용도별"})
    if "law_byeolpyo_fetch" in called and "record_ordinance_ruling" not in called:
        return _call("record_ordinance_ruling", {"verdict": "확인필요", "cited_count": 0,
                     "hojeok_path": "[stub] 조례별표+건축법령별표1 본문 확보 — 호목 멀티홉 해소는 실 LLM 필요"})
    # 의제
    jimok = state.get("jimok")
    if jimok and (jimok in _UIJAE or jimok in ("잡종지",)) and "record_uijae" not in called:
        items = []
        if jimok in _UIJAE:
            items.append({"trigger": f"지목={jimok}", "permit_name": _PERMIT[jimok], "stage_key": _UIJAE[jimok]})
        items.append({"trigger": "형질변경", "permit_name": "개발행위허가", "stage_key": "개발행위"})
        if state.get("road_side") == "맹지":   # #9 입지의제(맹지→사도)
            items.append({"trigger": "맹지(도로 미접)", "permit_name": "사도개설허가", "stage_key": "사도개설"})
        return _call("record_uijae", {"items": items})
    # 서류 (건축허가+의제단계+착공+사용승인, docs_for 지원분만)
    need = ["건축허가"] + [u["stage_key"] for u in state.get("uijae", [])] + ["착공신고", "사용승인"]
    done = {d["stage_key"] for d in state.get("documents", [])}
    for sk in need:
        if sk in _DOC_STAGES and sk not in done:
            return _call("docs_for_stage", {"stage_key": sk})
    # 규모·작성주체·규제효과
    if "scale_limits" not in state and "compute_scale" not in called:
        return _call("compute_scale", {"floor_area": state["floor_area"], "floor_count": state["floor_count"]})
    if "author" not in state and "author_rule_tool" not in called:
        return _call("author_rule_tool", {"floor_area": state["floor_area"], "work_type": state.get("work_type", "신축")})
    if state.get("reg_overlaps") and "reg_effect_resolve_tool" not in called:
        return _call("reg_effect_resolve_tool", {"reg_names": state["reg_overlaps"]})
    return AIMessage(content="조사 완료 — 도구 호출 종료")


def make_agent_node():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    if os.environ.get("FORCE_STUB"):   # 빠른 광역 검증용(LLM 우회)
        def agent_node(state):
            return {"messages": [stub_plan(state)]}
        return agent_node, "stub-planner(강제)"
    gms = os.environ.get("GMS_KEY")
    if gms:   # SSAFY GMS proxy (OpenAI 호환) — gpt-5.2
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model="gpt-5.2",
                         base_url="https://gms.ssafy.io/gmsapi/api.openai.com/v1",
                         api_key=gms).bind_tools(TOOLS)   # temperature 미설정(gpt-5 기본만 허용)
        def agent_node(state):
            return {"messages": [llm.invoke([("system", AGENT_SYSTEM)] + state["messages"])]}
        return agent_node, "LLM(GMS gpt-5.2)"
    if os.environ.get("ANTHROPIC_API_KEY"):
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0, max_tokens=2000).bind_tools(TOOLS)
        def agent_node(state):
            return {"messages": [llm.invoke([("system", AGENT_SYSTEM)] + state["messages"])]}
        return agent_node, "LLM(ChatAnthropic)"
    def agent_node(state):
        return {"messages": [stub_plan(state)]}
    return agent_node, "stub-planner(결정적)"
