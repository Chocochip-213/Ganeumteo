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
    reducer_fields = {n for n, h in S.GaneomteoState.__annotations__.items() if hasattr(h, "__metadata__")}
    missing = reducer_fields - fk
    assert not missing, f"reducer 필드가 fresh_state pre-init에 없음(누적 TypeError 위험): {sorted(missing)}"

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

def main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fail = 0
    for fn in fns:
        try: fn(); print(f"PASS {fn.__name__}")
        except Exception as e: fail += 1; print(f"FAIL {fn.__name__}: {e}")
    print("CONTRACTS OK" if not fail else f"CONTRACTS FAIL {fail}"); return 1 if fail else 0

if __name__ == "__main__": sys.exit(main())
