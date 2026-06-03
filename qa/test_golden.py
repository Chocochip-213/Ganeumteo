# -*- coding: utf-8 -*-
"""qa/test_golden.py — read-only 일반 불변식(MASTER_PLAN item 14). 특정 주소/업종/시설명 분기 X.
근거계약·fail-closed 회귀 그물: 근거없는 단정·bare 확인필요·세목 불일치 positive·허위 evidence를 도구가 거부하는지.
특정 케이스(건강보험공단 사무소·맹지 등)는 코드 로직 아니라 이 불변식의 regression INPUT일 뿐."""
import os, sys, traceback
os.environ.setdefault("FORCE_STUB", "1")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "agent"))
sys.path.insert(0, os.path.join(_ROOT, "lawlib"))
import tools, state as S


def _u(name, **kw):
    """도구 raw func 직접 호출(InjectedState 우회 — state 직접 전달). Command.update dict 반환."""
    cmd = tools.TOOLS_BY_NAME[name].func(tool_call_id="t", **kw)
    return getattr(cmd, "update", {}) or {}


def _ev_state(eid="law:테스트법|1", raw="이 시설은 해당 용도지역에서 건축할 수 있다", **extra):
    st = {"citations": [], "document_facts": {}, "evidence_records": {eid: {"evidence_id": eid, "source": "law", "raw_text": raw}}}
    st.update(extra)
    return st


def test_validate_rejects_fake_evidence():
    ok, _ = S.validate_basis_claims(_ev_state(), [{"evidence_id": "law:없는것|99", "claim_type": "legal_applicability", "quote_or_span": "x"}])
    assert not ok, "허위 evidence_id가 통과됨(ID-washing)"


def test_validate_quote_must_be_real():
    ok, _ = S.validate_basis_claims(_ev_state(raw="A B C"), [{"evidence_id": "law:테스트법|1", "claim_type": "legal_applicability", "quote_or_span": "원문에 없는 문장"}])
    assert not ok, "원문에 없는 quote가 통과됨(인용 위조)"


def test_user_fact_only_factual_input():
    st = {"document_facts": {"소유": "본인"}, "citations": [], "evidence_records": {}}
    okf, _ = S.validate_basis_claims(st, [{"evidence_id": "user_fact:소유", "claim_type": "factual_input"}])
    okl, _ = S.validate_basis_claims(st, [{"evidence_id": "user_fact:소유", "claim_type": "legal_applicability"}])
    assert okf and not okl, "user_fact가 법적 적용성 근거로 오용됨"


def test_static_only_calculation_basis():
    st = {"citations": [], "document_facts": {}, "evidence_records": {"static:x": {"evidence_id": "static:x", "source": "static", "raw_text": "500"}}}
    okc, _ = S.validate_basis_claims(st, [{"evidence_id": "static:x", "claim_type": "calculation_basis"}])
    okl, _ = S.validate_basis_claims(st, [{"evidence_id": "static:x", "claim_type": "legal_applicability"}])
    assert okc and not okl, "static 상수가 법적근거로 오용됨"


def test_reg_resolution_rejects_bare_uncertain():
    upd = _u("record_reg_resolution", reg_name="X구역", status="확인필요", blocking_level="normal", effect="", unresolved_by="none", state=_ev_state())
    assert upd.get("_reject_count") == 1, "bare 확인필요(unresolved_by 없음)가 통과됨"


def test_reg_resolution_rejects_unbacked_conclusion():
    upd = _u("record_reg_resolution", reg_name="X구역", status="해소", blocking_level="normal", effect="", basis_claims=[], state=_ev_state())
    assert upd.get("_reject_count") == 1, "근거없는 해소가 통과됨"


def test_reg_authority_needs_discretion_evidence():
    # authority punt 방지: 관할재량 근거(authority_discretion) 없이 authority 금지
    upd = _u("record_reg_resolution", reg_name="X구역", status="확인필요", blocking_level="normal", effect="",
             unresolved_by="authority", basis_claims=[{"evidence_id": "law:테스트법|1", "claim_type": "legal_applicability", "quote_or_span": "이 시설은"}], state=_ev_state())
    assert upd.get("_reject_count") == 1, "authority_discretion 근거 없이 authority punt 통과됨"


def test_landuse_no_positive_without_basis():
    # 세목 불일치 의심 케이스(intended=사무소, matched=건강보험공단 사무소)도 근거 없으면 가능 거부 — 특정 문자열 분기 아닌 일반 불변식
    upd = _u("record_landuse_resolution", intended_use="사무소", matched_node_desc="건강보험공단 사무소",
             api_reg_nm="가능", status="가능", basis_claims=[], state=_ev_state())
    assert upd.get("_reject_count") == 1, "근거없는 행위제한 '가능'이 통과됨"


def test_act_landuse_requires_use_classification():
    upd = _u("act_landuse", zone_ucode="UQA001", use_type="사무소", area_cd="11110", state={"use_classifications": []})
    assert "선결" in str(upd.get("messages", "")), "use_classification 없이 act_landuse 진행됨"


def test_verdict_rejects_positive_on_blocked_axis():
    upd = _u("record_verdict", final_verdict="가능", dimensions=[{"dimension": "조례", "status": "불가"}], basis_seq=[1], state=_ev_state())
    assert upd.get("_reject_count") == 1, "불가 축 위 '가능' 종합이 통과됨"


def test_verdict_rejects_danger_without_legal_basis():
    # P1(적대검수): '위험·금지'는 불가축에 법령 명시금지(legal_applicability) 근거 필수 — 데이터사실(factual_input)만으론 거부(미확인≠금지, 22㎡ 오해소 둔갑 차단). 특정 숫자/주소 분기 아닌 근거종류 불변식.
    st = {"document_facts": {"규모": "필지22㎡"}, "citations": [],
          "evidence_records": {"law:GB법|1": {"evidence_id": "law:GB법|1", "source": "law", "raw_text": "개발제한구역에서 건축물의 신축은 금지한다"}}}
    bad = _u("record_verdict", final_verdict="위험·금지",
             dimensions=[{"dimension": "규모", "status": "불가", "basis_claims": [{"evidence_id": "user_fact:규모", "claim_type": "factual_input"}]}], state=st)
    assert bad.get("_reject_count") == 1, "factual_input만 단 불가축으로 '위험·금지' 통과됨(데이터사실→법적금지 둔갑)"
    good = _u("record_verdict", final_verdict="위험·금지",
              dimensions=[{"dimension": "개발제한구역", "status": "불가", "basis_claims": [{"evidence_id": "law:GB법|1", "claim_type": "legal_applicability", "quote_or_span": "개발제한구역에서 건축물의 신축은 금지"}]}], state=st)
    assert good.get("_reject_count") != 1, "법령 명시금지 근거 단 정당한 '위험·금지'가 거부됨"


def test_verdict_rejects_unknown_unresolved_by():
    upd = _u("record_verdict", final_verdict="확인필요", dimensions=[{"dimension": "x", "status": "확인필요", "unresolved_by": "엉뚱값"}], state=_ev_state())
    assert upd.get("_reject_count") == 1, "비enum unresolved_by가 조용히 none으로 통과됨"


def test_verdict_rejects_fake_basis_claim():
    upd = _u("record_verdict", final_verdict="확인필요",
             dimensions=[{"dimension": "용도", "status": "확인필요", "unresolved_by": "agent", "basis_claims": [{"evidence_id": "law:가짜|1", "claim_type": "legal_applicability", "quote_or_span": "x"}]}],
             state=_ev_state())
    assert upd.get("_reject_count") == 1, "종합판정에 허위 evidence_id가 통과됨"


def test_stub_card_has_procedure_and_no_bare_uncertain():
    # stub 카드 구조: procedure_steps 존재 + verdict_labels의 확인필요 축은 unresolved_by 분류(bare 금지)
    sys.path.insert(0, os.path.join(_ROOT, "backend"))
    import proto_bridge as PB
    from state_init import fresh_state, make_config
    out = PB.GRAPH.invoke(fresh_state("경기도 양평군 양평읍 양근리 100", "카페", 264, 1), make_config()[1])
    card = out["_return"]["card"]
    assert "procedure_steps" in card, "card.procedure_steps 부재"
    assert card.get("verdict") in ("가능", "가능(조건부)", "위험·금지", "확인필요"), f"VERDICT_SPACE 위반:{card.get('verdict')}"
    for v in (card.get("verdict_labels") or []):
        if v.get("status") == "확인필요":
            assert v.get("unresolved_by", "none") != "none", f"bare 확인필요 축(unresolved_by 없음):{v.get('dimension')}"


def main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fail = 0
    for fn in fns:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except Exception as e:
            fail += 1; print(f"FAIL {fn.__name__}: {e}"); traceback.print_exc()
    print("GOLDEN OK" if not fail else f"GOLDEN FAIL {fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
