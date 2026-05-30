# -*- coding: utf-8 -*-
"""agent 노드 — LLM 키 있으면 ChatAnthropic(진짜 ReAct), 없으면 결정적 stub-planner.
stub은 실제 tool_calls를 발행 → LangGraph ToolNode+Command 브리지를 진짜로 구동(지능만 스크립트)."""
import os, uuid
from langchain_core.messages import AIMessage
from tools import TOOLS
import wf_docs_agent as DOC

AGENT_SYSTEM = """너는 대한민국 건축 인허가 사전진단 에이전트다. [주소/좌표 + 용도]를 받아 도구로 사실을 수집·판정해 진단 카드를 만든다.
[원칙] 1.사실은 도구 결과로만(기억 금지), 없으면 확인필요 기권. 2.모든 판정·서류·근거에 인용. 3.조례 별표가 "건축법 시행령 별표1 제N호 O목"을 참조하면 law_byeolpyo_fetch로 별표1(본문 전체) 가져와 호목 해소(멀티홉) — 별표 원문을 끝까지 읽어 해당 호목·용도 포함 여부를 직접 확인하라(중간 절단·일부만 보고 포기 금지). 해소 후 record_ordinance_ruling(verdict=...)로 결론을 커밋하되 verdict는 정확히 셋 중 하나: **가능**(제공된 별표 원문 호목이 해당 용도를 명시 허용) / **불가**(원문이 명시 금지) / **확인필요**(본문 미확보·호목 미해소·근거 불충분 — 기본값, 글자 일치 아니라 호목 의미로 판단하되 근거 못 찾으면 확인필요). 4.용도 해석은 네 몫 — 사용자 표현을 건축법 용도분류로 네가 해석하라(예: 카페→휴게/일반음식점). **사용자에게 '제1종/제2종' 같은 건축법 분류를 고르라고 묻지 마라(사용자는 모른다)** — 정말 모호할 때만 평이한 말로 업종을 되물어라.
[인자 전달] 각 도구의 인자는 이전 도구 결과(ToolMessage)에서 가져와라. 예: get_parcel이 준 PNU를 get_land_use(pnu=...)에 / geocode가 준 x,y를 get_parcel(x=,y=)에 / get_land_use가 준 UQ코드를 act_landuse(zone_ucode=)에 / get_parcel이 준 시군구·get_land_use의 용도지역을 ordin_byeolpyo_fetch(sigungu=,zone=)에. 인자 값이 없으면 그 도구를 호출하지 말고, 사용자 확정이 필요하면 request_human_input을 먼저. 'PNU'·'<값>'·'의제단계' 같은 자리표시자 문자열을 인자로 넣지 마라.
[권장흐름 — 고정 파이프라인 아님, 상황따라 생략·재배열·반복 가능] geocode→get_parcel→get_land_use→get_land_price→act_landuse →(act가 '조례확인필요'면)ordin_byeolpyo_fetch→law_byeolpyo_fetch→record_ordinance_ruling →(지목 전답과수원임야면)record_uijae →docs_for_stage→compute_scale→author_rule_tool→reg_effect_resolve_tool.
[규모·부담금 가이드 — 권장이며 강제순서 아님, 네 자율 판단]
 · 건폐율·용적률: 용도지역 확보 후 law_article_fetch('국토의 계획 및 이용에 관한 법률 시행령','84')로 건폐율 상한, ('…시행령','85')로 용적률 상한을 **원문서 직접 읽어** 그 %를 compute_envelope(land_area_m2=get_land_use의 대지면적, bcr_pct=, far_pct=)에 전달. 용적률 법정상한은 범위(예 계획관리 50~100%)라 도시계획조례 실제치를 못 읽었으면 envelope을 '법정상한 기준·실제치 확인필요'로 둔다. 대지면적이 없으면 envelope 생략.
 · 부설주차: law_byeolpyo_fetch('주차장법 시행령','1')로 별표1에서 **그 용도의 기준면적(㎡/대)**을 읽어 parking_quota(use_type=, floor_area=, base_area_m2=그 값)에 전달(별표1 본문의 숫자만 — 기억으로 채우지 말 것). 기준면적을 못 읽으면 호출하지 말고 확인필요.
 · 부담금: 농지전용(지목 전·답·과수원)이면 law_article_fetch('농지법 시행령','53')로 농업진흥지역 안/밖 율을 **원문에서 읽어** levy_estimate('농지보전부담금', land_price=공시지가, area_m2=대지면적, rate_pct=그 율)(율 숫자는 기억으로 채우지 말 것). 산지전용이면 levy_estimate('대체산림자원조성비')(단가 없음→확인필요). 개발행위 대상이면 levy_estimate('개발부담금')(설계前 금액 불가→부과대상만).
 · 일조(시행령§86)는 **전용주거·일반주거지역만** 대상 — 그 외 용도지역(계획관리·녹지·상업·공업)이면 일조 조문 fetch 불필요(용도지역을 네가 게이트). 경관·영향평가 대상 여부는 필요 시 해당 시행령 조문을 law_article_fetch로 읽어 케이스 면적·용도와 대조해 판단하되, 못 읽거나 규모 미달이면 '확인필요'로 둔다.
 · **무하드코딩 철칙**: 율·기준면적·단가·건폐율%는 전부 네가 fetch한 법령 원문에서 읽은 값만 인자로 전달한다. 기억으로 숫자를 지어내지 말 것(없으면 확인필요).
[docs_for_stage 호출법] stage_key는 반드시 실제 단계명만: '건축허가','착공신고','사용승인' 3개 + record_uijae로 기록한 의제의 stage_key 각각(농지전용/산지전용/개발행위). '의제단계' 같은 placeholder 문자열 금지. 의제 없으면 건축허가·착공신고·사용승인 3개만.
[병렬·실패] 서로 독립인 읽기 도구(get_land_use·get_land_price)는 한 메시지에 같이 호출해도 된다. 도구 결과가 실패/빈값이면 같은 인자로 재시도하지 말고 원인을 보고 다음 단계로 넘어가라(없는 값은 확인필요로 둔다).
[사고 노출] 도구를 부르기 전에 "왜 이 도구가 필요한지" 한 문장으로 먼저 말한 뒤 호출하라(사용자가 네 판단 과정을 본다). 단 도구 내부이름(law_byeolpyo_fetch·act_landuse 등)을 그대로 노출하지 말고 평이한 말로 행위를 설명하라(예: "law_byeolpyo_fetch로 확인" → "건축법 별표를 가져와 확인합니다").
[자기교정] 도구가 'EMPTY …후보:[...]' 같은 걸 주면 그 후보 중 맞는 값으로 인자만 바꿔 다시 호출하라(여러 이름·인자 시도). 한 경로가 막히면 다른 도구·다른 인자를 스스로 고려하라. 끝내 근거를 못 얻으면 확인필요로 둔다.
[중요·종료규칙] 이미 성공한 도구를 같은 인자로 또 부르지 마라. 위 항목을 다 모았으면 **도구를 부르지 말고** 짧게 '완료'라고만 답하라. 좌표가 이미 주어졌으면 geocode 생략하고 get_parcel부터."""

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
    # 신규 도메인 fetch 배선(stub은 LLM이 아니라 값을 못 읽으므로 산식도구에 값 날조 금지 →
    #  fetch 도구로 근거·levies 경로만 구동. 실제 율·기준면적 읽어 compute는 실 LLM 경로가 수행).
    if "law_article_fetch" not in called:   # 건폐율/용적률 상한 조문(§84) 라이브 인용
        return _call("law_article_fetch", {"law_name": "국토의 계획 및 이용에 관한 법률 시행령", "article": "84"})
    if "law_byeolpyo_fetch" not in called:   # 주차장법 시행령 별표1(기준면적 원문) 라이브 인용
        return _call("law_byeolpyo_fetch", {"law_name": "주차장법 시행령", "byeolpyo_kw": "1"})
    if "levy_estimate" not in called:        # 부담금 경로 구동(지목별 유형; 율 미전달=확인필요로 정직 강등)
        jimok = state.get("jimok")
        if jimok in ("전", "답", "과수원"):
            return _call("levy_estimate", {"levy_type": "농지보전부담금"})
        if jimok == "임야":
            return _call("levy_estimate", {"levy_type": "대체산림자원조성비"})
        return _call("levy_estimate", {"levy_type": "개발부담금"})
    return AIMessage(content="조사 완료 — 도구 호출 종료")


def make_agent_node():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    if os.environ.get("FORCE_STUB"):   # 빠른 광역 검증용(LLM 우회)
        def agent_node(state):
            return {"messages": [stub_plan(state)]}
        return agent_node, "stub-planner(강제)"
    gms = os.environ.get("GMS_KEY")
    if gms:   # SSAFY GMS proxy (OpenAI 호환) — gpt-5.2 (토큰 절약: pro 아님)
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
