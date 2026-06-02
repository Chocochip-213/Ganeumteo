# -*- coding: utf-8 -*-
"""절차 프레임 불변식 — 코드 무판정·누락방지·근거계약 회귀 그물. offline·결정적."""
import os, sys, traceback
os.environ.setdefault("FORCE_STUB", "1")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "agent"))
sys.path.insert(0, os.path.join(_ROOT, "lawlib"))
import tools, wf_procedure_agent as PROC

def _u(name, **kw):   # qa/test_golden.py 패턴 — .func 직접호출(InjectedState/ToolCallId 우회)
    cmd = tools.TOOLS_BY_NAME[name].func(tool_call_id="t", **kw)
    return getattr(cmd, "update", {}) or {}

# 불변식 1 — 코드 무판정(가장 중요): frame()은 applies·status·verdict·순서판정을 만들지 않는다.
def test_frame_emits_no_verdict():
    for f in PROC.frame():
        assert set(f) == {"step_id","order","stage_key","law","articles","gate_hint","is_doc_stage"}
        assert "applies" not in f and "status" not in f and "verdict" not in f
        assert isinstance(f["articles"], list) and f["articles"]   # 법조 포인터 실재
        assert f["law"]

# 불변식 2 — 표준 골격 망라(누락방지 핵심): 빠뜨리기 쉬운 단계가 프레임에 실재.
def test_frame_covers_standard_skeleton():
    keys = {f["step_id"] for f in PROC.frame()}
    assert {"사전결정","건축심의","해체","감리보고","대장등재","유지관리"} <= keys

# 불변식 3 — 도구 동형성: 도구는 procedure_frame(라우팅)만 쓰고 procedure_steps(커밋)는 안 쓴다.
def test_tool_writes_routing_not_verdict():
    upd = _u("procedure_framework_tool")
    assert "procedure_frame" in upd and "procedure_steps" not in upd
    assert all("applies" not in f for f in upd["procedure_frame"])

# 불변식 4 — 근거 없는 applies=no 강등(기존 계약 회귀방지, tools.py record_procedure_steps 게이트).
def test_no_evidence_applies_no_downgraded():
    upd = _u("record_procedure_steps",
             steps=[{"step_id":"해체","applies":"no","status":"근거확보"}], state={})
    s = upd["procedure_steps"][0]
    assert s["applies"]=="unknown" and s["status"]=="확인필요" and s["unresolved_by"]=="agent"

# 불변식 5 — stub E2E 완주(B/E C1 데드락 회귀 그물): completed로 끝나고 표준 단계 망라.
def test_stub_e2e_completes_with_full_timeline():
    sys.path.insert(0, os.path.join(_ROOT, "backend"))
    import proto_bridge as PB
    from state_init import fresh_state, make_config
    out = PB.GRAPH.invoke(fresh_state("경기도 양평군 양평읍 양근리 100", "카페", 264, 1), make_config()[1])
    env = out["_return"]
    assert env["terminal_reason"] == "completed", f"stub 캡소진(데드락) 회귀: {env['terminal_reason']}"
    keys = {p["step_id"] for p in env["card"]["procedure_steps"]}
    assert {"사전결정","건축심의","해체","감리보고","대장등재","유지관리"} <= keys, "표준 단계 누락(stub)"
    assert all(p["status"]=="확인필요" for p in env["card"]["procedure_steps"]), "stub은 전부 미판정이어야"

# 불변식 6 — 검증맵 조문 일치(회귀 고정): 정기점검 §13, 의제결합=건축허가(§11), 해체법.
def test_articles_match_verified_map():
    fr = {f["step_id"]: f for f in PROC.frame()}
    assert "13" in fr["유지관리"]["articles"]   # 정기점검 §13(맵 정정 반영)
    assert fr["건축허가"]["articles"] == ["11"] and fr["사용승인"]["articles"] == ["22"]
    assert fr["해체"]["law"] == "건축물관리법"

# 불변식 7 — gate_hint verdict 누설 금지(적대검증 봉쇄): 결론어 0.
def test_gate_hint_has_no_verdict_token():
    _BAN = ("applies=no", "applies=yes", "불가", "면제됨", "해당없음", "해당 없음")
    for f in PROC.frame():
        for w in _BAN:
            assert w not in f["gate_hint"], f"gate_hint verdict 누설: {f['step_id']} / {w}"

def main():
    fns = [v for k,v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fail = 0
    for fn in fns:
        try: fn(); print(f"PASS {fn.__name__}")
        except Exception as e: fail += 1; print(f"FAIL {fn.__name__}: {e}"); traceback.print_exc()
    print("PROC OK" if not fail else f"PROC FAIL {fail}"); return 1 if fail else 0

if __name__ == "__main__": sys.exit(main())
