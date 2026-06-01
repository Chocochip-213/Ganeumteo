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


_STEP_HARDCAP = 24      # agent 방문 하드캡(무한루프 방지)
_GUARD_BOUNCE_CAP = 19  # 이 이상이면 guard 바운스 중단(진행)


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
    # 의제 누락은 jimok 코드매칭이 아니라 record_uijae 호출여부로 판단(전용 의제 판정은 LLM 몫).
    # 서류 전수검사(아래)가 기록된 의제 stage_key를 need에 합산하므로 의제 커버리지는 거기서 일원 enforce.
    if state.get("pnu") and "record_uijae" not in called:
        miss.append("의제")
    if state.get("_delegated") and "ordin_byeolpyo_fetch" not in called:
        miss.append("조례별표")
    if state.get("pnu"):   # med: 호출여부가 아니라 단계 커버리지 검사
        doc_stages = {d.get("stage_key") for d in state.get("documents", []) if d.get("status") == "전수확보"}   # 실패(확인필요) 단계는 미커버 — 성공만 카운트(실패가 완료로 둔갑 방지)
        # 건축허가(=신축/증축)를 가져왔거나 아직 아무 단계도 안 가져왔으면 신축 3단계 완결성 요구. 그 외(용도변경 등 LLM이 다른 stage 선택)는 그 단계만 — 신축 가정 안 함.
        base = {"건축허가", "착공신고", "사용승인"} if ("건축허가" in doc_stages or not doc_stages) else set(doc_stages)
        need = base | {u.get("stage_key") for u in state.get("uijae", [])}
        if not need.issubset(doc_stages):
            miss.append("서류전수:" + ",".join(sorted(need - doc_stages)))
        # 조건부('해당시만') 서류 미판정 검사 — 에이전트가 케이스로 판정(필요시 사용자 질의)해야 종료(최상위 호만, 목 제외)
        _mok = "가나다라마바사아자차카타파하"
        cond_keys = {(d.get("stage_key"), _norm_ho(it.get("ho"))) for d in state.get("documents", [])
                     for it in (d.get("items") or [])
                     if it.get("conditional") and not any(c in str(it.get("ho", "")) for c in _mok)}
        assessed = {(a.get("stage_key"), _norm_ho(a.get("ho"))) for a in state.get("cond_assessments", [])}
        if cond_keys - assessed:
            miss.append(f"조건부판정:{len(cond_keys - assessed)}건")
        else:
            # unknown 조건부(권원·공동소유·사전결정·분할납부 등 사용자만 아는 사실)인데 사용자에게 한 번도 안 물었으면 → 묻으라고 바운스(검수 #1: unknown이 완료로 통과하던 것). 이미 물은 뒤의 unknown·stub은 수용(과바운스 방지).
            _unk = {(a.get("stage_key"), _norm_ho(a.get("ho"))) for a in state.get("cond_assessments", []) if str(a.get("applies")) == "unknown"} & cond_keys
            _is_stub = os.environ.get("FORCE_STUB") or os.environ.get("APP_MODE") == "stub"
            if _unk and "request_human_input" not in called and not _is_stub:
                miss.append(f"조건부 사용자확인:{len(_unk)}건")
    if miss and (state.get("_steps", 0) - state.get("_turn_base_steps", 0)) < _GUARD_BOUNCE_CAP and not stalled:
        # 제어신호는 사용자 발화로 위장하지 않는다 — <system-reminder>로 명시(Claude Code 패턴). 모델은 이를 자동점검 지시로 읽음.
        return {"_incomplete": True, "messages": [HumanMessage(f"<system-reminder>완결성 자동점검(사용자 발화 아님): 아직 미확인 {miss}. 해당 도구로만 마저 조회하고, 끝나면 도구 없이 '완료'라 답하라.</system-reminder>")]}
    if miss:   # 캡 도달 — 더 못 채움 → 기권 사유로 남기고 진행
        return {"_incomplete": False, "abstentions": [{"node": "completeness_guard", "사유": f"미충족 {miss}(스텝 캡)"}]}
    return {"_incomplete": False}


def route_after_guard(state):
    if state.get("_incomplete"):
        return "agent"
    substantive = [c for c in state.get("citations", []) if c.get("source") in ("law", "ordin", "data")]
    if not substantive and not state.get("act_verdict"):   # #7 판정 근거 전무(vworld 입지만)→기권
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
    if state.get("act_verdict") == "가능(법령직접)":   # 도구계약 enum 정확비교(substring 금지)
        return "가능(조건부)" if conditional else "가능"
    return "확인필요"  # 입지 미확보(API실패)도 여기 = 안전 degrade(거짓 가능 방지)


def build_reasoning(state):
    """결정적 논증 골격(부록 E). 각 단계 citation. 서술은 (실 LLM) compose가."""
    steps, seq = [], 0
    def add(kind, fact, basis, infer="", leads=""):
        nonlocal seq; seq += 1
        return {"seq": seq, "kind": kind, "fact": fact, "basis": basis,
                "infer": infer, "leads": leads, "status": "확정" if basis else "확인필요"}
    steps.append(add("입지", f"지목={state.get('jimok')} 용도지역={state.get('zone')} 도로접면={state.get('road_side')}", "vworld"))
    if state.get("act_verdict"):
        steps.append(add("행위제한", f"{state.get('zone')} {state['use_type']}", "data.go.kr 1613000", state.get("act_verdict")))
    for jv in state.get("jorye_verdicts", []):
        steps.append(add("조례호목해소", jv.get("ordin_name") or "조례 별표",
                         "ordin" if jv.get("verdict") != "확인필요" else None, jv.get("reason", ""), jv.get("verdict", "")))
    for u in state.get("uijae", []):
        steps.append(add("의제", f"{u['trigger']} → {u['permit_name']}", "law"))
    for r in state.get("reg_effects", []):
        steps.append(add("규제효과", r["reg_name"], r.get("law_name"), r.get("effect", "")))
    sl = state.get("scale_limits")
    if sl:
        steps.append(add("규모임계", "연면적/층수 임계", "law"))
    env = state.get("envelope")   # 건폐율·용적률 envelope(가늠치 — verdict 무관) — compute_scale와 분리 키
    if env and env.get("max_building_area") is not None:
        steps.append(add("규모가늠", f"최대건축면적 {env.get('max_building_area')}㎡·최대연면적 {env.get('max_floor_area')}㎡·약식층수 {env.get('approx_floors')}",
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
    # fail-closed(deny-first): 개발제한/농업진흥 등 강한 규제 겹침 + 행위제한 조문 미확보면 거짓 '가능' 막아 확인필요 보류(코드가 위험·금지 단정 안 함).
    regs = (state.get("reg_overlaps") or []) + [state.get("zone") or ""]
    strong_regs = [r for r in regs if ("개발제한" in r) or ("농업진흥" in r)]
    if strong_regs and verdict in ("가능", "가능(조건부)", "조건부"):
        grounded = {e.get("reg_name") for e in state.get("reg_effects", []) if e.get("status") == "근거확보"}
        if not any(any(sr in (g or "") or (g or "") in sr for g in grounded) for sr in strong_regs):
            verdict = "확인필요"
            out.setdefault("abstentions", []).append({"node": "build_reasoning", "gate": "strong_regs", "사유": f"강한 행위제한 규제중첩 {strong_regs} — 행위제한 조문 미확보, 사람검토 필요"})
    # 선결조건(접도) fail-closed: 맹지(도로 미접)는 신축의 기본 선결(건축법§44 접도의무). 도로지정·사도개설(§45/사도법)로
    #  해소 가능성이 record_uijae로 검토되지 않은 채 '가능'이면 신축 성립 자체가 불확실 → 확인필요 보류(거짓 가능 방지).
    #  용도변경 등 비신축은 새 접도의무가 생기지 않으므로 제외(doc_stages로 신축 여부 판별 — work_type 가정 안 함).
    if state.get("road_side") == "맹지" and verdict in ("가능", "가능(조건부)", "조건부"):
        _ds = {d.get("stage_key") for d in state.get("documents", [])}
        _is_sinchuk = ("건축허가" in _ds) or not (_ds & {"용도변경", "대수선"})
        _road_resolved = bool({u.get("stage_key") for u in state.get("uijae", [])} & {"사도개설", "도로지정"})
        if _is_sinchuk and not _road_resolved:
            verdict = "확인필요"
            out.setdefault("abstentions", []).append({"node": "build_reasoning", "gate": "no_road_access",
                "사유": "맹지(도로 미접) — 신축은 건축법§44 접도의무가 선결. 도로지정·사도개설(§45/사도법) 가능성 미검토 → 사람검토 필요"})
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
        "verdict_labels": state.get("verdict_labels", []),   # 다차원 판정 축(LLM이 케이스마다 정함) — 종합 verdict 옆에 투명 표시
        "document_facts": state.get("document_facts", {}),   # 사용자가 확인해준 서류판단 사실(권원·사전결정 등) — '확인된 사실' 노출
        "legal_reasoning": state.get("legal_reasoning"),
        "uijae": state.get("uijae"),
        "documents": [{"stage": d["stage_key"], "count": d.get("count", 0), "status": d["status"],
                       "law": d.get("law", ""), "article": d.get("article", ""),
                       "when_note": d.get("when_note", ""), "when_law": d.get("when_law", ""),
                       "when_title": d.get("when_title", ""), "when_quote": d.get("when_quote", ""),
                       "author_note": d.get("author_note", ""),
                       "apply_title": d.get("apply_title", ""), "apply_hwp": d.get("apply_hwp", ""),
                       "apply_pdf": d.get("apply_pdf", ""), "items": _doc_items(d)}
                      for d in state.get("documents", [])],
        "scale_limits": _merge_scale_card(state),   # compute_scale + envelope(분리키) 표시 병합
        "parking_req": state.get("parking_req"),       # 부설주차 N대(parking_quota)
        "levies": state.get("levies", []),             # 부담금(농지보전·대체산림·개발) — 금액 없으면 status=확인필요
        "author": state.get("author"),
        "term_notes": state.get("term_notes"),   # 진단맥락 용어설명(프론트 popover)
        "reg_effects": state.get("reg_effects"),
        "citations": len(state.get("citations", [])),
        "abstentions": state.get("abstentions", []),
    }
    return {"_card": card, "terminal_reason": "completed"}


_STATUS = {"completed": "완료", "verdict_resolved": "조기종료", "need_human": "사람검토",
           "step_capped": "부분완료(단계 한도)", "no_grounds": "근거 부족(확인필요)", "context_overflow": "재시도필요(컨텍스트 초과)",
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
        over = state.get("_steps", 0) - state.get("_turn_base_steps", 0)
        subst = [c for c in state.get("citations", []) if c.get("source") in ("law", "ordin", "data")]
        tr = "step_capped" if over >= _STEP_HARDCAP else ("no_grounds" if (not subst and not state.get("act_verdict")) else "need_human")
    return {"terminal_reason": tr,
            "_card": {"verdict": "확인필요", "terminal": tr,
                      "사유": state.get("abstentions") or "근거(citation) 0건",
                      "입지": {"지목": state.get("jimok"), "용도지역": state.get("zone"),
                              "도로접면": state.get("road_side")},
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
    from langgraph.checkpoint.memory import MemorySaver
    return b.compile(checkpointer=MemorySaver()), mode   # H3: interrupt(HITL) 가능하게
