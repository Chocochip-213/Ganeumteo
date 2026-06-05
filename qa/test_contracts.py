# -*- coding: utf-8 -*-
"""계약 불변식 — 디커플링/reducer 회귀 그물. offline·결정적(검수 X-5)."""
import os, sys, traceback
os.environ.setdefault("FORCE_STUB", "1")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "agent"))
sys.path.insert(0, os.path.join(_ROOT, "backend"))
import state as S
from state_init import fresh_state

# 불변식 D1 — operator.add/merge reducer 필드는 fresh_state가 전부 pre-init해야 한다.
# 미초기화 시 첫 append가 reducer(None,[x]) → operator.add(None,...) TypeError(검수 D1: levies 실발생).
def test_reducer_fields_preinit():
    fk = set(fresh_state("경기도 양평군 양평읍 양근리 100", "카페", 100, 1).keys())
    # 누적/병합 리듀서(operator.add·_merge_*·_keep_true)는 None 첫-write서 TypeError → pre-init 필수.
    # _keep_last·_keep_truthy_first는 None을 안전 처리(빈값=미설정)하고 stub/라우팅 `"X" not in state` 게이트를 보존해야 하므로 pre-init 면제(오히려 pre-init하면 게이트 깨짐 — 라이브 회귀 실측: 양평 카페 citations 5→3, ordin 추출 누락).
    SAFE = {S._keep_last, S._keep_truthy_first}
    need_preinit = {n for n, h in S.GaneomteoState.__annotations__.items()
                    if hasattr(h, "__metadata__") and (h.__metadata__[0] not in SAFE)}
    missing = need_preinit - fk
    assert not missing, f"누적/병합 리듀서 필드가 fresh_state pre-init에 없음(None 첫-write TypeError 위험): {sorted(missing)}"

# 불변식 D2 — backend _STATUS(종료사유 라벨 단일소스) 키 == frontend verdict.js STATUS_KO 키.
# 불일치 시 프론트가 종료사유를 '부분완료(확인 권장)'로 뭉갬(검수 D2: tool_budget_exhausted 실발생).
def test_status_label_keys_match():
    import re
    from graph import _STATUS
    js = open(os.path.join(_ROOT, "frontend", "verdict.js"), encoding="utf-8").read()
    block = js[js.index("STATUS_KO ="):]
    block = block[:block.index("}")]
    fe = set(re.findall(r"(\w+)\s*:", block))
    missing = set(_STATUS) - fe
    assert not missing, f"backend _STATUS 키가 frontend STATUS_KO에 없음(종료사유 라벨 뭉개짐): {sorted(missing)}"

# 불변식 D3 — _delegated는 OR 리듀서 필드여야 한다(병렬 도구가 한 superstep에 동시 set → InvalidUpdateError 차단).
# plain 필드로 되돌리면 act_landuse·ordin_*가 한 턴에 병렬 호출될 때 그래프 전체가 중단된다(검수: 라이브 crash 실발생).
def test_delegated_concurrent_merge():
    reducer_fields = {n for n, h in S.GaneomteoState.__annotations__.items() if hasattr(h, "__metadata__")}
    # 한 superstep에 병렬/중복 도구가 동시 write할 수 있는 단일값 채널은 전부 리듀서(Annotated)여야 — plain이면 InvalidUpdateError로 그래프 crash(라이브 실발생). systemic 동시성 수정(Claude Code read-only병렬/write직렬 철학을 채널레벨로).
    for ch in ("_delegated", "doc_index_hit", "envelope", "scale_limits", "parking_req", "author", "term_notes",
               "_llm_verdict", "_verdict_round", "act_landuse_raw", "act_reg_raw", "procedure_frame",
               "zone", "zone_ucodes", "land_area", "road_side", "_xy", "pnu"):
        assert ch in reducer_fields, f"{ch}가 리듀서(Annotated) 아님 — 병렬/중복 도구 동시 write 시 InvalidUpdateError(라이브 crash)"
    assert S._keep_true(True, True) is True and S._keep_true(None, True) is True, "OR 리듀서가 동시 True를 병합 안 함"
    assert S._keep_true(False, True) is True and S._keep_true(False, False) is False, "_keep_true OR 의미 위반"
    # _keep_last: last-write-wins(빈값이면 기존 유지). crash 대신 병합.
    assert S._keep_last({}, {"a": 1}) == {"a": 1} and S._keep_last({"a": 1}, {}) == {"a": 1}, "_keep_last 빈값 처리 위반"
    assert S._keep_last({"a": 1}, {"b": 2}) == {"b": 2}, "_keep_last last-write-wins 위반"
    # _keep_truthy_first(road_side): None이 채워진 값을 덮지 않음(get_land_use None이 get_parcel 맹지값 보존) + 둘 다 채워지면 뒤 값. 순서-비의존.
    assert S._keep_truthy_first(None, "맹지") == "맹지" and S._keep_truthy_first("맹지", None) == "맹지", "_keep_truthy_first None-보존 위반(맹지 fail-closed 회귀)"
    assert S._keep_truthy_first("한면", "맹지") == "맹지", "_keep_truthy_first 둘다채움 last 위반"

# 불변식 D4 — HITL 답변(document_facts 키)은 user_fact:<key>로 인용 가능해야 한다(record_* 근거계약).
# 안 되면 work_type 등 user_fact 근거 커밋이 거부루프→record_loop(빈 진단)으로 떨어진다(검수: 라이브 crash 실발생).
def test_human_fact_citable():
    ids = S.collect_evidence_ids({"document_facts": {"answer": "철거 후 신축"}})
    assert "user_fact:answer" in ids, "HITL 답변이 인용 가능한 evidence_id(user_fact:<key>)로 노출 안 됨"
    assert S._claim_kind_ok("factual_input", "user_fact:answer"), "user_fact는 factual_input 근거로 허용돼야(거부루프 방지)"

def main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fail = 0
    for fn in fns:
        try: fn(); print(f"PASS {fn.__name__}")
        except Exception as e: fail += 1; print(f"FAIL {fn.__name__}: {e}")
    print("CONTRACTS OK" if not fail else f"CONTRACTS FAIL {fail}"); return 1 if fail else 0

if __name__ == "__main__": sys.exit(main())
