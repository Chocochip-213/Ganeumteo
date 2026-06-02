# -*- coding: utf-8 -*-
"""구조 경계 회귀테스트(U10) — 시나리오 열거가 아니라 구조 불변식만 어서트. offline·결정적.
마라톤(U1~U9) 다수 편집 후 모듈 경계·도구계약·status-creep·가드집합이 안 깨졌는지 그물."""
import sys, os, traceback
os.environ.setdefault("FORCE_STUB", "1")   # 실 LLM 셋업 회피(import만 검증)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "agent"))
sys.path.insert(0, os.path.join(_ROOT, "lawlib"))


def test_import_boundary():
    """agent/lawlib 모듈이 순환·깨짐 없이 import(다수 편집 후 import 경계)."""
    import graph, tools, state, agent, wf_reg_agent, law_fetch  # noqa: F401
    assert callable(graph.build_graph)


def test_tools_command_contract():
    """모든 @tool이 StructuredTool(name·func) — TOOLS/ToolNode 계약 불변."""
    import tools
    assert len(tools.TOOLS) >= 10
    for t in tools.TOOLS:
        assert hasattr(t, "name") and hasattr(t, "func"), f"{t!r} @tool 아님"
    assert set(tools.TOOLS_BY_NAME) == {t.name for t in tools.TOOLS}


def test_reg_seed_status_creep():
    """REG_SEED 라우팅힌트는 영원히 '확인필요'(근거확보 false-grounding 봉쇄). REG_LAW 미매치 kw=fetch 0."""
    import wf_reg_agent as R
    seed_only = [s["kw"] for s in R.REG_SEED if not any(t[0] in s["kw"] for t in R.REG_LAW)]
    assert seed_only, "REG_SEED-only kw 없음(테스트 전제 깨짐)"
    res = R.resolve(seed_only)   # 전 seed-only kw → seed 분기, 네트워크 0(REG_LAW 미매치). 검수B F1: 첫개만 말고 전수
    bad = [r for r in res if r["상태"] != "확인필요"]
    assert res and not bad, f"REG_SEED status-creep: {bad}"


def test_record_reject_guard_set():
    """U1 doom-loop 가드 대상 = 근거없는 단정 거부 도구(record_verdict·ordinance·reg_resolution + 신규 분류도구)."""
    import graph
    assert {"record_verdict", "record_ordinance_ruling", "record_reg_resolution",
            "record_use_classification", "record_landuse_resolution", "record_work_type"} <= graph._RECORD_TOOLS


def test_new_contract_tools_injectedstate():
    """item 0c: 결론성 도구 9종 + 계산 3종이 존재하고 근거계약 검증용 InjectedState(state 파라미터)를 받는다."""
    import inspect, tools
    concl = ["record_reg_resolution", "record_verdict", "record_ordinance_ruling", "record_landuse_resolution",
             "record_use_classification", "record_procedure_steps", "record_work_type", "record_uijae", "assess_conditional_docs"]
    calc = ["parking_quota", "levy_estimate"]   # author_rule_tool은 §23① fetch 기반(값 인자 없음)
    by = tools.TOOLS_BY_NAME
    for nm in concl + calc:
        assert nm in by, f"{nm} TOOLS 미등록"
    # 신규 결론성 도구는 state(InjectedState) 파라미터 보유(근거 실재 검증 경유)
    for nm in ["record_reg_resolution", "record_verdict", "record_landuse_resolution", "record_use_classification",
               "record_work_type", "record_procedure_steps", "assess_conditional_docs", "parking_quota", "levy_estimate"]:
        params = inspect.signature(by[nm].func).parameters
        assert "state" in params, f"{nm} InjectedState(state) 미수신 → 근거계약 검증 불가"


def test_no_hardcoded_industry_branch():
    """item 8·13 무하드코딩: graph/tools 코드(주석·docstring 제외)에 특정 업종/구역명 if 분기 0."""
    import re
    for fn in ("graph.py", "tools.py"):
        p = os.path.join(_ROOT, "agent", fn)
        with open(p, encoding="utf-8") as f:
            for ln in f:
                s = ln.strip()
                if s.startswith("#") or s.startswith('"') or "description=" in s or "_tm(" in s or "note=" in s:
                    continue
                # if/elif 분기에 업종/구역명 리터럴이 박히면 과적합
                if re.match(r"^(if|elif)\b", s) and re.search(r"피시방|인터넷컴퓨터게임|상대보호구역|교육환경보호", s):
                    raise AssertionError(f"{fn}: 업종/구역명 코드 분기 — {s[:80]}")


def main():
    fns = [test_import_boundary, test_tools_command_contract, test_reg_seed_status_creep, test_record_reject_guard_set,
           test_new_contract_tools_injectedstate, test_no_hardcoded_industry_branch]
    fail = 0
    for fn in fns:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except Exception as e:
            fail += 1; print(f"FAIL {fn.__name__}: {e}"); traceback.print_exc()
    print("BOUNDARY OK" if not fail else f"BOUNDARY FAIL {fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
