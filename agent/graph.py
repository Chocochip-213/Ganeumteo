# -*- coding: utf-8 -*-
"""ReAct 그래프 — 명세 부록 G1. agent ⇄ tools 루프 + 완결성 가드 + build_reasoning + compose + finalize/abstain."""
import os
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from langgraph.errors import GraphBubbleUp   # interrupt(HITL)·control-flow 신호 — 절대 삼키면 안 됨
from langchain_core.messages import HumanMessage, ToolMessage
from state import GaneomteoState
from tools import TOOLS
from agent import make_agent_node
import wf_procedure_agent as _PROCFR   # PROC_FRAME is_doc_stage floor(검수 H-1)
_DOC_FRAME_STAGES = frozenset(f["stage_key"] for f in _PROCFR.PROC_FRAME if f.get("is_doc_stage"))


def _wrap_tool_call(request, execute):
    """도구 예외를 <tool_use_error> tool_result + abstention으로 환류(bare throw 금지) — 18툴 일괄 예외안전.
    스키마검증(ToolInvocationError)은 execute가 이미 메시지화하니 통과, 그 외 예외(KeyError·API 비정상 등)만 잡아
    모델이 읽고 자기교정할 결과로 돌린다. 배치 크래시·dangling tool_use 제거 + abstention으로 sse가 '확인필요' 정직 노출."""
    tc = request.tool_call
    name = tc.get("name", "")
    if request.tool is None:                          # 미등록/오타 도구명
        return ToolMessage(f"<tool_use_error>알 수 없는 도구 '{name}' — 등록된 도구명으로 다시 호출하라</tool_use_error>",
                           tool_call_id=tc["id"], name=name, status="error")
    try:
        return execute(request)
    except GraphBubbleUp:                             # interrupt(HITL)·control-flow → 전파(삼키면 입력요청 깨짐)
        raise
    except Exception as e:                            # 스키마 외 예외 → 크래시 대신 정직 환류
        em = f"{type(e).__name__}: {str(e) or repr(e)}"[:300]
        return Command(update={
            "messages": [ToolMessage(f"<tool_use_error>{em}</tool_use_error>", tool_call_id=tc["id"], name=name, status="error")],
            "abstentions": [{"node": name, "사유": f"도구 예외 {type(e).__name__}"}],
            "_toolcalls": [name]})   # 시도 기록 → 가드·stub 무한 재호출 방지(fail-closed abstain)


_STEP_HARDCAP = 56      # agent 방문 하드캡(무한루프 방지). 근거계약 흐름 + R1 risk-layer 다중규제(reg당 ~2턴)로 44→56(15~18 overlap 입지 완주, heavy-reg 검증서 마진 3 관찰). 폭주는 _reject_count가 별도 차단.
_GUARD_BOUNCE_CAP = 46  # 이 이상이면 guard 바운스 중단(진행). R1 다중규제 헤드룸 36→46.
_REJECT_CAP = 3         # record 도구 연속 거부 N회면 doom-loop 조기종료(확인필요). step-cap(over≥36)으로도 종료되나 그 전에 끊어 ~32왕복 낭비차단 + 정직한 종료사유(record_loop). '무한방지'가 아니라 '조기종료'(검수B 실측: U1없이도 36왕복서 step_capped 종료)
_RECORD_TOOLS = {"record_verdict", "record_ordinance_ruling", "record_reg_resolution",
                 "record_use_classification", "record_landuse_resolution", "record_work_type"}   # 판정/해소/분류 커밋 도구(근거없는 단정 거부→U1 doom-loop 반복추적 대상)


def _norm_ho(ho):
    """조건부 서류 호 매칭키 정규화 — 표기차('1'·'1.'·'제1호'·'1호')만 흡수.
    앞 '제'·뒤 '호'·양끝 마침표/공백만 정리(글로벌 치환 금지 → 식별자 안 깨지고 목 '1.가.'도 '1'과 안 섞임)."""
    s = str(ho or "").strip().rstrip(".").strip()
    if s.startswith("제"):
        s = s[1:].strip()
    if s.endswith("호"):
        s = s[:-1].strip()
    return s.strip()


def route_after_agent(state):
    base_s = state.get("_turn_base_steps", 0)            # 후속턴: 이번 invoke 기준(thread 누적 아님)
    base_t = state.get("_turn_base_tools", 0)
    if state.get("terminal_reason") in ("site_geocode_failed", "aborted", "error", "llm_error", "context_overflow"):  # H4 조기종료 + LLM 실패/컨텍스트초과 즉시 중단(다시하기 유도)
        return "abstain"
    last = state["messages"][-1]
    over = state.get("_steps", 0) - base_s
    if getattr(last, "tool_calls", None):   # 펜딩 도구는 캡보다 먼저 실행해 ToolMessage로 매칭 — dangling tool_use(검수 #1) 방지
        if state.get("_reject_count", 0) >= _REJECT_CAP and any(tc.get("name") in _RECORD_TOOLS for tc in last.tool_calls):
            return "abstain"   # U1: 판정도구 연속거부≥N + 또 판정 재시도 = doom-loop → 조기종료(확인필요). any()=record가 끼면 단독이든 fetch 병렬동반이든 끊음(거부 누적 후 곁다리 fetch는 회복보다 flailing 가능성↑·fail-closed라 안전·step-cap 백스톱). 단독 비판정 도구(fetch만)는 통과(구조신호만, 도메인파싱 0).
        return "abstain" if over >= _STEP_HARDCAP + 12 else "tools"   # 폭주 한계서만 abstain(abstain은 LLM 재호출 없어 미매칭 tool_call 무해)
    if over >= _STEP_HARDCAP:    # 텍스트 응답(펜딩 도구 없음) 시점에만 하드캡 — 안전. followup 누적 잠금 방지(검수 AF-3)
        return "completeness_guard"
    if len(state.get("_toolcalls", [])) <= base_t and str(getattr(last, "content", "") or "").strip():
        return "chat_end"   # 이번 턴 새 도구 0 + 텍스트만 = 대화(진단 아님). 후속턴 잡담도 chat_end 도달(검수 AF-1)
    return "completeness_guard"


def chat_end(state):
    """대화 종료 — 에이전트가 도구 없이 텍스트로 답하면(인사·잡담·되물음) 그 텍스트 그대로 반환(진단 카드 없음)."""
    last = state["messages"][-1]
    return {"terminal_reason": "chat",
            "_return": {"status": "대화", "chat": str(getattr(last, "content", "") or "").strip()}}


def completeness_guard(state):
    """결정적 누락 점검(부록 G4-2). 빠지면 agent 복귀 — 단 _steps 캡 내에서만(루프 방지)."""
    msgs = state.get("messages") or []
    last = msgs[-1] if msgs else None
    stalled = (last is not None and not getattr(last, "tool_calls", None)
               and not str(getattr(last, "content", "") or "").strip())   # agent 빈 메시지 정체 → 바운스해도 또 빔
    called = set(state.get("_toolcalls", []))
    miss = []
    if "get_parcel" not in called:
        miss.append("입지")
    if state.get("pnu") and "get_building_register" not in called and not (os.environ.get("FORCE_STUB") or os.environ.get("APP_MODE") == "stub"):
        miss.append("건물대장(work_type)")   # 건물대장 조회 강제(검수 P0) — pnu 있는데 미조회 채 완료 금지(미조회 신축 단정 차단). 조회 결과 반영(건물있음→용도변경)은 프롬프트/LLM 몫(코드 교차검증=하드코딩이라 안 함). stub 면제(품질가드).
    # 의제 누락은 jimok 코드매칭이 아니라 record_uijae 호출여부로 판단(전용 의제 판정은 LLM 몫).
    # 서류 전수검사(아래)가 기록된 의제 stage_key를 need에 합산하므로 의제 커버리지는 거기서 일원 enforce.
    if state.get("pnu") and "record_uijae" not in called:
        miss.append("의제(record_uijae 호출 — 없으면 items=[]로)")
    if state.get("_delegated") and "ordin_byeolpyo_fetch" not in called:
        miss.append("조례별표")
    if state.get("reg_overlaps") and "reg_effect_resolve_tool" not in called:
        miss.append("규제조회")   # 중첩규제(reg_overlaps) 있으면 근거조회 강제 — 미조회 채 '가능' 차단(호출여부 게이트, dedup 무관·robust). 영향판정·critical 표식은 record_reg_resolution/LLM 몫(결함1 fix). stub은 agent.py:98서 호출하므로 자연 satisfy.
    _is_stub = bool(os.environ.get("FORCE_STUB") or os.environ.get("APP_MODE") == "stub")
    if state.get("pnu"):   # substantive diagnosis(입지 확보)에서만 절차/완료 게이트 — geocode 실패·잡담은 면제(item 10 조건부)
        # item 10: 절차판정 선행(신축3단계 기본값 제거) — record_procedure_steps 없으면 절차 누락(비신축 신축흐름 강제 안 함)
        if "record_procedure_steps" not in called:
            # 프레임 미검토 채 절차 미커밋이면 프레임부터 환기(표준 단계 누락 방지). 프레임 받았으면 단계 구성은 LLM 자율
            # — 단계집합·phase 망라를 하드 검사하지 않는다(그러면 코드가 절차 verdict를 박음=무하드코딩 위반). 망라성은 프레임+근거게이트 소프트압력.
            if "procedure_framework_tool" not in called:
                miss.append("절차프레임(procedure_framework_tool 호출 — 표준 건축행정절차 단계 체크리스트 받기)")
            else:
                miss.append("절차판정(record_procedure_steps 호출 — 프레임 각 단계 applies 판정)")
        # 서류 = 적용 절차(requires_documents=true) + 의제 stage만 요구(신축 가정 제거). list_status=전수확보만 커버(실패=미커버).
        proc = [p for p in state.get("procedure_steps", []) if isinstance(p, dict) and p.get("applies") != "no"]
        doc_stages = {str(d.get("stage_key") or "").strip() for d in state.get("documents", []) if d.get("list_status", d.get("status")) == "전수확보"}
        doc_need = set()
        for p in proc:
            _sk = str(p.get("stage_key") or "").strip()
            # 검수 H-1: applies=yes 서류단계(프레임 is_doc_stage)는 requires_documents 누락해도 전수 요구 — LLM이 서류단계 누락해 거짓완료하는 fail-OPEN 차단. stub(전부 applies=unknown)엔 미발동→데드락 없음(불변식5 보존). applies 판정은 여전히 LLM.
            if p.get("requires_documents") or (_sk in _DOC_FRAME_STAGES and p.get("applies") == "yes"):
                doc_need.update(str(k).strip() for k in (p.get("related_document_stage_keys") or [p.get("stage_key")]) if k)
        doc_need.update(str(u.get("stage_key")).strip() for u in state.get("uijae", []) if u.get("stage_key"))
        if not doc_need.issubset(doc_stages):
            miss.append("서류전수:" + ",".join(sorted(doc_need - doc_stages)))
        # 조건부('해당시만') 서류 미판정 검사(최상위 호만, 목 제외)
        _mok = "가나다라마바사아자차카타파하"
        cond_keys = {(d.get("stage_key"), _norm_ho(it.get("ho"))) for d in state.get("documents", [])
                     for it in (d.get("items") or [])
                     if it.get("conditional") and not any(c in str(it.get("ho", "")) for c in _mok)}
        assessed = {(a.get("stage_key"), _norm_ho(a.get("ho"))) for a in state.get("cond_assessments", [])}
        if cond_keys - assessed:
            miss.append(f"조건부판정:{len(cond_keys - assessed)}건")
        else:
            _unk = {(a.get("stage_key"), _norm_ho(a.get("ho"))) for a in state.get("cond_assessments", []) if str(a.get("applies")) == "unknown"} & cond_keys
            if _unk and "request_human_input" not in called and not _is_stub:
                miss.append(f"조건부 사용자확인:{len(_unk)}건")
        # item 1·2·10: per-overlap 규제 완료게이트 — 각 reg_overlap에 record_reg_resolution(resolution_committed) 필수(stub 면제). reg_effect_resolve_tool 조회만으론 완료 금지.
        if not _is_stub and state.get("reg_overlaps"):
            _lr = _resolved_regs(state)
            _miss_reg = [r for r in state["reg_overlaps"] if r and not (_lr.get(r) or {}).get("resolution_committed")]
            if _miss_reg:
                miss.append("규제해소(record_reg_resolution로 각 규제 판정):" + ",".join(str(r) for r in _miss_reg[:5]))
        # A M-2: 건축가부 별표를 fetch했으면 판정 커밋 강제 — record_ordinance_ruling 누락 시 조례축 silent 차단(stub 면제). 가능/불가/확인필요 내용은 LLM(코드는 커밋 presence만).
        # 별표 fetch 실패경로는 확인필요 JoryeVerdict 자동적재(tools.py:303) → jorye_verdicts 비면 성공fetch인데 미커밋 = 그 갭만 잡음. envelope용 ordin_article_fetch 인용은 별표 판정과 무관해 제외(별표 도구 호출 기준).
        if not _is_stub and "ordin_byeolpyo_fetch" in called and not state.get("jorye_verdicts"):
            miss.append("조례판정(record_ordinance_ruling — 읽은 조례 별표로 가부 커밋, 미해소면 확인필요+unresolved_by)")
        # §0 2b: agent-미해결 루프백 — reg_effects/verdict_labels에 unresolved_by=agent 남으면 더 조사 강제(stub 면제). 최종 카드 잔존은 user/authority/data_unavailable/tool_budget_exhausted만.
        if not _is_stub:
            _vl = state.get("_verdict_round") if state.get("_verdict_round") is not None else state.get("verdict_labels", [])
            _agent_un = ([r.get("reg_name") for r in _resolved_regs(state).values() if r.get("unresolved_by") == "agent"]
                         + [v.get("dimension") for v in _vl if isinstance(v, dict) and v.get("unresolved_by") == "agent"])
            if _agent_un:
                miss.append("미해결재조사(agent):" + ",".join(str(x) for x in _agent_un[:4]))
    if miss and (state.get("_steps", 0) - state.get("_turn_base_steps", 0)) < _GUARD_BOUNCE_CAP and not stalled:
        # 제어신호는 사용자 발화로 위장하지 않는다 — <system-reminder>로 명시(Claude Code 패턴).
        return {"_incomplete": True, "messages": [HumanMessage(f"<system-reminder>완결성 자동점검(사용자 발화 아님): 아직 미확인 {miss}. 해당 도구로만 마저 조회·판정하고(확인필요는 unresolved_by로 분류, 더 조사 가능하면 직접 조사), 끝나면 도구 없이 '완료'라 답하라.</system-reminder>")]}
    if miss:   # 캡 도달 — 0f/0g: 더 못 채움. cap honesty(_capped→compose가 tool_budget_exhausted) + agent 미해결→tool_budget_exhausted 변환(append-only)
        upd = {"_incomplete": False, "_capped": True,
               "abstentions": [{"node": "completeness_guard", "사유": f"미충족 {miss}(스텝 캡)", "attempted_tools": sorted(called)}]}
        upd.update(_convert_agent_unresolved(state))   # 0g: agent→tool_budget_exhausted 새 row(reg_effects append·_verdict_round 재구성)
        return upd
    return {"_incomplete": False}


def route_after_guard(state):
    if state.get("_incomplete"):
        return "agent"
    substantive = [c for c in state.get("citations", []) if c.get("source") in ("law", "ordin", "data")]
    if not substantive and not state.get("landuse_resolutions"):   # #7 판정 근거 전무(vworld 입지만)→기권. act_verdict 코드신호 대신 LLM 커밋(landuse_resolution)·substantive citation으로 판단(item 3)
        return "abstain"
    return "build_reasoning"


def _derive_verdict(state):
    # 조건부 수식어는 raw 지목 코드매칭이 아니라 LLM이 record_uijae로 기록한 의제 신호에서만 도출(전용허가 의제=조건부 근거).
    conditional = bool(state.get("uijae"))
    jv = state.get("jorye_verdicts") or []
    real = [v for v in jv if v.get("verdict") not in ("확인필요", "", None)]  # H2: 실패append 무시
    pick = real[-1] if real else (jv[-1] if jv else None)
    if pick is not None:
        v = pick.get("verdict", "")
        if v == "가능":
            return "가능(조건부)" if conditional else "가능"
        if v in ("불가", "위험·금지"):
            return "위험·금지"
        return "확인필요"
    lr = _latest_landuse(state)   # item 3: 코드 API 승격(act_verdict) 제거 → LLM이 record_landuse_resolution로 커밋한 '가능'만 긍정
    if lr and lr.get("status") == "가능":
        return "가능(조건부)" if conditional else "가능"
    return "확인필요"  # 입지 미확보·행위제한 미판정도 여기 = 안전 degrade(거짓 가능 방지)


def _resolved_regs(state):
    """reg_effects를 reg_name별 1엔트리. item 2: resolution_committed=True(LLM 영향판정) 우선, 없을 때만 fetch row(근거확보/확인필요).
    단순 최신이면 fetch row가 LLM 판정을 덮을 수 있어 → committed가 fetch를 덮게(완료 우선). read-time dedup(reducer 무변경=SqliteSaver 안전)."""
    committed, fetched = {}, {}
    for e in state.get("reg_effects", []):
        nm = e.get("reg_name")
        if not nm:
            continue
        (committed if e.get("resolution_committed") else fetched)[nm] = e   # 각자 최신(뒤 우선)
    out = dict(fetched)
    out.update(committed)   # committed(영향판정 완료)가 fetch(자료확보)를 덮음
    return out


def _latest_landuse(state):
    """record_landuse_resolution 최신 1엔트리(마지막 커밋). 없으면 None. 코드 act_verdict 승격 대체(item 3) — 행위제한 판정 입력은 이것만."""
    lrs = [l for l in (state.get("landuse_resolutions") or []) if isinstance(l, dict)]
    return lrs[-1] if lrs else None


def _latest_work_type(state):
    """record_work_type 최신 확정 WorkTypeResolution(맹지/절차 게이트가 읽는 단일원, item 9·0d). 없으면 None(보수적). 코드는 raw work_type/문자열 추론 안 봄."""
    wts = [w for w in (state.get("work_type_resolutions") or []) if isinstance(w, dict)]
    return wts[-1] if wts else None


def _convert_agent_unresolved(state):
    """0g: 스텝캡 도달시 agent(더 조사 가능했으나 캡 소진) → tool_budget_exhausted 변환(무한루프 차단·정직 표시).
    reg_effects=새 row append(committed selector가 최신 집음), verdict_labels=_verdict_round 재구성(last-write-wins). 기존 row 수정 아님(append-only)."""
    out = {}
    new_regs = []
    for r in _resolved_regs(state).values():
        if r.get("unresolved_by") == "agent":
            r2 = dict(r); r2["unresolved_by"] = "tool_budget_exhausted"; r2["resolution_committed"] = True
            r2["effect"] = (str(r.get("effect", "")) + " [스텝캡 소진: 자동 미해소]").strip()
            new_regs.append(r2)
    if new_regs:
        out["reg_effects"] = new_regs
    _vl = state.get("_verdict_round") if state.get("_verdict_round") is not None else state.get("verdict_labels", [])
    if any(isinstance(v, dict) and v.get("unresolved_by") == "agent" for v in _vl):
        out["_verdict_round"] = [{**v, "unresolved_by": "tool_budget_exhausted"} if isinstance(v, dict) and v.get("unresolved_by") == "agent" else v for v in _vl]
    return out


def build_reasoning(state):
    """결정적 논증 골격(부록 E). 각 단계 citation. 서술은 (실 LLM) compose가."""
    steps, seq = [], 0
    def add(kind, fact, basis, infer="", leads=""):
        nonlocal seq; seq += 1
        return {"seq": seq, "kind": kind, "fact": fact, "basis": basis,
                "infer": infer, "leads": leads, "status": "확정" if basis else "확인필요"}
    steps.append(add("입지", f"지목={state.get('jimok')} 용도지역={state.get('zone')} 도로접면={state.get('road_side')}", "vworld"))
    _lr = _latest_landuse(state)   # item 3: 행위제한 row는 LLM 판정(record_landuse_resolution)만 근거. act_landuse_raw는 probe(확정 아님).
    if _lr:
        _lok = _lr.get("status") in ("가능", "불가", "조건필요")   # LLM 커밋 판정=확정(근거), 확인필요=확인필요
        steps.append(add("행위제한", f"{state.get('zone')} {_lr.get('intended_use') or state.get('use_type')}",
                         "data.go.kr 1613000" if _lok else None, _lr.get("status", "")))
    elif state.get("act_landuse_raw"):   # raw 조회만(판정 미커밋) → 확정 아님
        steps.append(add("행위제한", f"{state.get('zone')} {state.get('use_type')}", None, "raw 조회만(판정 미커밋)"))
    for jv in state.get("jorye_verdicts", []):
        steps.append(add("조례호목해소", jv.get("ordin_name") or "조례 별표",
                         "ordin" if jv.get("verdict") != "확인필요" else None, jv.get("reason", ""), jv.get("verdict", "")))
    for u in state.get("uijae", []):
        steps.append(add("의제", f"{u['trigger']} → {u['permit_name']}", "law"))
    for r in _resolved_regs(state).values():   # reg_name별 최신(resolution 우선) — fetch+resolution 중복 step 방지(F1)
        # item 12: 근거확보(fetch 자료확보)≠확정. LLM이 record_reg_resolution로 커밋한 해소/해당없음만 확정(resolution_committed). 미커밋·미해소·확인필요=확인필요.
        _rok = r.get("resolution_committed") and r.get("status") in ("해소", "해당없음")
        steps.append(add("규제효과", r["reg_name"], (r.get("law_name") or "ordin") if _rok else None, r.get("effect", "")))
    sl = state.get("scale_limits")
    if sl:
        steps.append(add("규모임계", "연면적/층수 임계", "law"))
    env = state.get("envelope")   # 건폐율·용적률 envelope(가늠치 — verdict 무관) — compute_scale와 분리 키
    if env and env.get("max_building_area") is not None:
        _ref = "참고(신축 가정·현재 직접 적용 아님) " if env.get("reference_only") else ""   # U6: LLM-set 플래그만 읽어 정직표시(verdict 입력 아님 — verdict_basis_seq는 행위제한/조례만, 불변)
        _scope = f" [적용범위:{env.get('area_scope')}]" if env.get("area_scope") else ""
        steps.append(add("규모가늠", f"{_ref}최대건축면적 {env.get('max_building_area')}㎡·최대연면적 {env.get('max_floor_area')}㎡·약식층수 {env.get('approx_floors')}{_scope}",
                         "law", env.get("envelope_note", "")))
    pr = state.get("parking_req")
    if pr and pr.get("status") == "산출":   # 부설주차 N대(가늠치 — verdict 무관)
        steps.append(add("부설주차", f"{pr.get('use_type')} {pr.get('floor_area')}㎡ → {pr.get('spaces')}대",
                         "law", pr.get("note", "")))
    elif pr:
        steps.append(add("부설주차", "부설주차 대수", None, pr.get("note", "")))
    for lv in state.get("levies", []):   # 부담금(금액 없으면 status=확인필요 → basis None)
        steps.append(add("부담금", f"{lv.get('levy_type')}: {lv.get('formula','')}".strip(),
                         "law" if lv.get("status") == "산출" else None,
                         (f"≈{lv.get('amount'):,}원" if lv.get("amount") is not None else lv.get("note", ""))))
    # 판정 책임 = LLM(record_verdict). 비stub에서 record_verdict 없으면 코드가 긍정판정 생성 금지 — _derive는 downgrade(위험·금지/확인필요)만(검수 P0 record_verdict 필수화).
    _llm = state.get("_llm_verdict")
    _is_stub = bool(os.environ.get("FORCE_STUB") or os.environ.get("APP_MODE") == "stub")
    if _llm:
        verdict = _llm
    elif _is_stub:
        verdict = _derive_verdict(state)   # stub=결정적 스캐폴드(품질검증 아님)라 _derive 허용
    else:
        _d = _derive_verdict(state)
        verdict = _d if _d in ("위험·금지", "확인필요") else "확인필요"   # 코드는 긍정 못 만듦(record_verdict 없으면 확인필요)
    out = {}
    # 안전게이트(key_uncertain·강한규제·맹지)는 LLM verdict에도 동일 적용 → over-promise 차단(downgrade만). 강등 시 gate 흔적 남김(검수 B3).
    key_uncertain = any(s["status"] == "확인필요" and s["kind"] in ("행위제한", "조례호목해소") for s in steps)
    if key_uncertain and verdict in ("가능", "가능(조건부)", "조건부"):   # H5: 핵심단계 근거없으면 강등
        verdict = "확인필요"
        out.setdefault("abstentions", []).append({"node": "build_reasoning", "gate": "key_uncertain", "사유": "핵심단계(행위제한/조례) 근거 미확보 → 확인필요 강등"})
    # fail-closed(완료계약): 중첩규제(reg_overlaps)를 LLM이 record_reg_resolution로 판정 안 했거나(미판정/조회만) 핵심(critical)인데 미해소면 '가능' 강등 — 핵심축 미해소 위에 '가능' 못 얹음(결함1). 코드는 reg명 의미 안 봄, LLM-set status/blocking_level만 == 비교(strong_regs 개발제한/농업진흥 하드코딩 대체). 해소·해당없음·미해소(normal)=통과, 미판정·조회만(근거확보)·확인필요·미해소(critical)=차단(fail-safe).
    _rmap = _resolved_regs(state)
    def _reg_ok(r):
        e = _rmap.get(r, {}); st, bl = e.get("status"), e.get("blocking_level")
        return st in ("해소", "해당없음") or (st == "미해소" and bl != "critical")
    reg_block = [r for r in (state.get("reg_overlaps") or []) if r and not _reg_ok(r)]
    if reg_block and verdict in ("가능", "가능(조건부)", "조건부"):
        verdict = "확인필요"
        out.setdefault("abstentions", []).append({"node": "build_reasoning", "gate": "reg_unresolved", "사유": f"미판정·핵심미해소 중첩규제 {reg_block[:5]}({len(reg_block)}건) → 해소판정 필요(사람검토)"})
    # truncation gate(U5): '가능' 조례판정이 '끝까지 못 읽힌 별표'에 의존하면 단정 불가 → 강등(확인필요). 코드는 캡 산술 truncated boolean·source_id 집합매칭만(본문 의미 0).
    #  P1a(검수A): source_id별 — 완독창(truncated=False, offset 페이징으로 끝 도달)이 하나라도 있으면 면제. 모든 창이 잘렸을 때만 '미완독'(과강등 방지·offset 정합). P1b: 위험·금지(jorye '불가')는 안전종착이라 별도 강등 안 함(과경고는 안전, 가능계열만).
    _by_src = {}
    for c in state.get("citations", []):
        if c.get("source_id"):
            _by_src.setdefault(c["source_id"], []).append(bool(c.get("truncated")))
    _trunc_ids = {sid for sid, fl in _by_src.items() if fl and all(fl)}
    if _trunc_ids and verdict in ("가능", "가능(조건부)", "조건부"):
        _bad = [jv for jv in state.get("jorye_verdicts", [])
                if jv.get("verdict") == "가능" and (set(jv.get("relied_source_ids") or []) & _trunc_ids)]
        if _bad:
            verdict = "확인필요"
            out.setdefault("abstentions", []).append({"node": "build_reasoning", "gate": "truncated_basis", "사유": "조례 '가능' 판정 근거 별표가 끝까지 안 읽힘(완독창 없음) — offset으로 이어읽거나 더 좁은 별표로 전문 확인 필요(확인필요)"})
    # 선결조건(접도) fail-closed: 맹지(도로 미접)는 신축의 기본 선결(건축법§44 접도의무). 도로지정·사도개설(§45/사도법)로
    #  해소 가능성이 검토되지 않은 채 '가능'이면 신축 성립 자체가 불확실 → 확인필요 보류(거짓 가능 방지).
    #  item 9: 신축 여부 판별을 doc_stages substring이 아니라 구조화 WorkTypeResolution으로(문자열 추론 금지·LLM 커밋값). 미확정=보수적(선결 적용).
    if state.get("road_side") == "맹지" and verdict in ("가능", "가능(조건부)", "조건부"):
        _wt = _latest_work_type(state)
        _wtype = (_wt or {}).get("work_type") if (_wt and _wt.get("status") == "확정") else None
        _is_newbuild = (_wtype in ("신축", "증축")) or _wtype is None   # 신축/증축=접도선결, 용도변경/대수선/해체=면제, 미확정=fail-closed
        _road_resolved = bool({u.get("stage_key") for u in state.get("uijae", [])} & {"사도개설", "도로지정"})
        if _is_newbuild and not _road_resolved:
            verdict = "확인필요"
            out.setdefault("abstentions", []).append({"node": "build_reasoning", "gate": "no_road_access",
                "사유": "맹지(도로 미접) — 신축/증축은 건축법§44 접도의무가 선결. 도로지정·사도개설(§45/사도법) 가능성 미검토 → 사람검토 필요(work_type 미확정시 보수적 적용)"})
    # 근거 seq = 판정 방향에 맞는 단계만(검수 #5): 긍정이면 '가능' 단계, 확인필요/금지면 '막은/불확실' 단계
    if verdict in ("가능", "가능(조건부)", "조건부"):
        _basis = [s["seq"] for s in steps if s["kind"] in ("행위제한", "조례호목해소") and s.get("status") != "확인필요"]
    else:
        _basis = [s["seq"] for s in steps if s.get("status") == "확인필요" and s["kind"] in ("행위제한", "조례호목해소")]
    out["legal_reasoning"] = {"steps": steps, "verdict": verdict, "verdict_basis_seq": _basis}
    out["verdict"] = verdict
    return out


def _merge_scale_card(state):
    """카드 표시용: compute_scale(에너지/구조)·compute_envelope(max_*, 분리키) 저장분 병합(notes 합침)."""
    sl, env = state.get("scale_limits") or {}, state.get("envelope") or {}
    if not sl and not env:
        return None
    out = {**sl, **env}
    notes = list(sl.get("notes") or []) + [n for n in (env.get("notes") or []) if n not in (sl.get("notes") or [])]
    if notes:
        out["notes"] = notes
    return out


def _dedup_docs(docs):
    """P3(적대검수): 같은 stage_key 다중 documents 행 병합 — 전수확보·items많은·count큰 행 채택, 빈 placeholder/superseded 행 제거.
    출력(카드) 위생만(state.documents 불변 → 완결성가드 영향 0). reg_effects 중복제거(F1)와 동형. 의미판정 0=무하드코딩."""
    def _score(x):
        return ((x.get("list_status", x.get("status")) == "전수확보"), len(x.get("items") or []), x.get("count", 0) or 0)
    best = {}
    for d in docs:
        if not isinstance(d, dict):
            continue
        k = str(d.get("stage_key") or "")
        if k not in best or _score(d) > _score(best[k]):
            best[k] = d
    return list(best.values())


def compose(state):
    """진단 카드 조립(부록 D1.2). 사실 재생성 없이 State 값만. (실 LLM이면 서술 강화)."""
    _ca = {(a.get("stage_key"), _norm_ho(a.get("ho"))): a for a in state.get("cond_assessments", [])}
    def _doc_items(d):   # 조건부 서류 항목에 에이전트 판정(applies·assess_reason) 병합
        out = []
        for it in (d.get("items") or []):
            it2 = dict(it)
            if it.get("conditional"):
                a = _ca.get((d.get("stage_key"), _norm_ho(it.get("ho"))))
                if a:
                    it2["applies"] = a.get("applies"); it2["assess_reason"] = a.get("reason")
            out.append(it2)
        return out
    card = {
        "verdict": state.get("verdict"),
        "verdict_labels": (state["_verdict_round"] if state.get("_verdict_round") is not None
                           else state.get("verdict_labels", [])),   # 최신 record_verdict 라운드 라벨만(다라운드 stale 축 제거, U3). is not None=빈 dims 라운드도 그대로 0축(검수B: or면 빈[]가 stale fallback)

        "document_facts": state.get("document_facts", {}),   # 사용자가 확인해준 서류판단 사실(권원·사전결정 등) — '확인된 사실' 노출
        "legal_reasoning": state.get("legal_reasoning"),
        "uijae": state.get("uijae"),
        "documents": [{"stage": d["stage_key"], "count": d.get("count", 0), "status": d["status"],
                       "list_status": d.get("list_status", d.get("status")),   # item 5: 목록확보(해당여부는 items[].applies_status)
                       "law": d.get("law", ""), "article": d.get("article", ""),
                       "when_note": d.get("when_note", ""), "when_law": d.get("when_law", ""),
                       "when_title": d.get("when_title", ""), "when_quote": d.get("when_quote", ""),
                       "author_note": d.get("author_note", ""),
                       "apply_title": d.get("apply_title", ""), "apply_hwp": d.get("apply_hwp", ""),
                       "apply_pdf": d.get("apply_pdf", ""), "items": _doc_items(d)}
                      for d in _dedup_docs(state.get("documents", []))],
        "scale_limits": _merge_scale_card(state),   # compute_scale + envelope(분리키) 표시 병합
        "parking_req": state.get("parking_req"),       # 부설주차 N대(parking_quota)
        "levies": state.get("levies", []),             # 부담금(농지보전·대체산림·개발) — 금액 없으면 status=확인필요
        "author": state.get("author"),
        "term_notes": state.get("term_notes"),   # 진단맥락 용어설명(프론트 popover)
        "reg_effects": list(_resolved_regs(state).values()),   # reg_name별 최신(resolution 우선) 중복 제거(검수 F1)
        "citations": len(state.get("citations", [])),
        "abstentions": state.get("abstentions", []),
        # item 10: 인허가 절차 타임라인(documents와 분리) — order 정렬, applies=no(비해당)는 접어 표시(프론트)
        "procedure_steps": sorted([p for p in state.get("procedure_steps", []) if isinstance(p, dict)],
                                  key=lambda p: p.get("order", 0)),
        "landuse_resolution": _latest_landuse(state),   # 행위제한 LLM 판정(act_landuse_raw는 probe)
    }
    # 0f cap 정직성: 완결성 캡 도달(_capped)이면 completed 아님 → tool_budget_exhausted(status≠완료). 정상 완료만 completed.
    return {"_card": card, "terminal_reason": "tool_budget_exhausted" if state.get("_capped") else "completed"}


_STATUS = {"completed": "완료", "verdict_resolved": "조기종료", "need_human": "사람검토",
           "step_capped": "부분완료(단계 한도)", "no_grounds": "근거 부족(확인필요)", "context_overflow": "재시도필요(컨텍스트 초과)",
           "record_loop": "확인필요(판정 근거 반복 미확보)",
           "tool_budget_exhausted": "부분완료(추가 조사 한도 — 미해결 잔존)",   # 0f: 캡 도달 미해결 — completed와 구분(status≠완료)
           "site_geocode_failed": "재입력필요", "fallback_extract_failed": "부분완료",
           "error": "부분완료", "aborted": "중단", "llm_error": "재시도필요"}


def finalize(state):
    """부록 D2: 종료 반환계약 ReturnEnvelope(항상 채워 반환)."""
    tr = state.get("terminal_reason", "completed")
    env = {"terminal_reason": tr, "status": _STATUS.get(tr, "완료"),
           "card": state.get("_card") or {"verdict": state.get("verdict"), "사유": state.get("abstentions")},
           "abstentions": state.get("abstentions", [])}
    return {"terminal_reason": tr, "_return": env}


def abstain(state):
    tr = state.get("terminal_reason")
    if not tr:   # 종료사유 해상도 — 왜 기권했나 분리(검수 A3: 폭주 vs 근거부족 vs 사람검토)
        if state.get("_reject_count", 0) >= _REJECT_CAP:   # U1: 판정 도구 반복거부로 강제종료 — 근거 못 단 채 단정 반복
            tr = "record_loop"
        else:
            over = state.get("_steps", 0) - state.get("_turn_base_steps", 0)
            subst = [c for c in state.get("citations", []) if c.get("source") in ("law", "ordin", "data")]
            tr = "step_capped" if over >= _STEP_HARDCAP else ("no_grounds" if (not subst and not state.get("landuse_resolutions")) else "need_human")
    return {"terminal_reason": tr,
            "_card": {"verdict": "확인필요", "terminal": tr,
                      "사유": state.get("abstentions") or "근거(citation) 0건",
                      "입지": {"지목": state.get("jimok"), "용도지역": state.get("zone"),
                              "도로접면": state.get("road_side")},
                      # step_capped·need_human이면 부분진단도 가치 — 모은 결과 노출(빈 진단 아님)
                      "verdict_labels": (state.get("_verdict_round") if state.get("_verdict_round") is not None else state.get("verdict_labels", [])),
                      "procedure_steps": sorted([p for p in state.get("procedure_steps", []) if isinstance(p, dict)], key=lambda p: p.get("order", 0)),
                      "reg_effects": list(_resolved_regs(state).values()),
                      "landuse_resolution": _latest_landuse(state),
                      "uijae": state.get("uijae", []),
                      "documents": [{"stage": d.get("stage_key"), "list_status": d.get("list_status", d.get("status")), "count": d.get("count", 0)} for d in state.get("documents", [])],
                      "citations": len(state.get("citations", []))}}


def build_graph():
    raw_agent, mode = make_agent_node()
    def agent_node(state):                       # _steps 증가(루프 하드캡용)
        r = raw_agent(state)
        r["_steps"] = 1                          # operator.add → 누적
        return r
    b = StateGraph(GaneomteoState)
    b.add_node("agent", agent_node)
    b.add_node("tools", ToolNode(TOOLS, wrap_tool_call=_wrap_tool_call))   # 예외→tool_result+abstention 환류(크래시 방지)
    b.add_node("completeness_guard", completeness_guard)
    b.add_node("build_reasoning", build_reasoning)
    b.add_node("compose", compose)
    b.add_node("finalize", finalize)
    b.add_node("abstain", abstain)
    b.add_node("chat_end", chat_end)
    b.add_edge(START, "agent")
    b.add_conditional_edges("agent", route_after_agent,
                            {"tools": "tools", "completeness_guard": "completeness_guard", "abstain": "abstain", "chat_end": "chat_end"})
    b.add_edge("tools", "agent")
    b.add_conditional_edges("completeness_guard", route_after_guard,
                            {"agent": "agent", "build_reasoning": "build_reasoning", "abstain": "abstain"})
    b.add_edge("build_reasoning", "compose")
    b.add_edge("compose", "finalize")
    b.add_edge("abstain", "finalize")
    b.add_edge("chat_end", END)
    b.add_edge("finalize", END)
    import sqlite3
    from langgraph.checkpoint.sqlite import SqliteSaver
    _is_stub = bool(os.environ.get("FORCE_STUB") or os.environ.get("APP_MODE") == "stub")
    # 실 LLM=단일파일 영속(재시작 후 thread resume) · stub/테스트=in-memory(파일 오염·무한증가 방지·결정적). 단일파일까지만(Postgres·락 과설계 안 함).
    # ⚠️ 운영 파일 db는 checkpoint가 thread별 무한 누적(retention/TTL 없음 — 데모 가정) → 주기적으로 ganeomteo_checkpoints.db* 삭제로 리셋(운영 전환시 delete_thread retention 잡 추가).
    _db = ":memory:" if _is_stub else (os.environ.get("GANEOMTEO_DB") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ganeomteo_checkpoints.db"))   # GANEOMTEO_DB=병렬 검수 시 thread별 격리 db(락경합 회피)
    _conn = sqlite3.connect(_db, check_same_thread=False, isolation_level=None)   # isolation_level=None=autocommit(langgraph from_conn_string canonical) → interrupt(HITL) write가 프로세스 종료 전 즉시 커밋·영속 → cross-process resume 보장. check_same_thread=False=FastAPI 멀티스레드 invoke(+SqliteSaver 내부 Lock 직렬화)
    if _db != ":memory:":
        _conn.execute("PRAGMA journal_mode=WAL")          # 동시 reader/writer 락경합 완화
        _conn.execute("PRAGMA busy_timeout=5000")         # 락대기 5s — 병렬 thread/process 동시 invoke 시 즉시 'database is locked' 회피
    _saver = SqliteSaver(_conn); _saver.setup()             # 체크포인트 테이블 생성(idempotent)
    return b.compile(checkpointer=_saver), mode             # H3: interrupt(HITL) sqlite 영속 — 실 LLM은 프로세스 재시작 후에도 thread resume
