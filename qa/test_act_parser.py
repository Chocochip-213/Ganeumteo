# -*- coding: utf-8 -*-
"""act_detail 4필드 XML 파서 회귀 — DTarLandUseInfo 실응답 골든(UQA111 채워짐 / UQA001 빈값→abstention).
파서가 REG_NM·LU_REF_LAW_NM1·NODE_DESC·DEF_REF 4필드를 뽑는지·빈응답을 []로 거르는지 **형태검증**(verdict 단정 아님 — 워크플로우 #2)."""
import os, sys, json
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lawlib"))
from wf_e2e_live import _parse_act_items

_FX = os.path.join(_ROOT, "qa", "fixtures")
def _raw(n): return json.load(open(os.path.join(_FX, n), encoding="utf-8"))["raw"]   # raw XML(euc-kr 디코드됨)을 .json에 래핑(qa/fixtures/*.txt는 gitignore)

# UQA111(제1종전용주거 actRegList 채워짐) → REG_NM 있는 item에서 4필드 전부 추출
def test_act_parser_extracts_four_fields():
    items = _parse_act_items(_raw("act_DTarLandUse_UQA111.json"))
    assert len(items) >= 1, "REG_NM 있는 item을 못 뽑음(euc-kr→텍스트 파서 회귀)"
    it = items[0]
    assert set(it.keys()) == {"reg", "ref_law", "node", "def_ref"}, f"4필드 키 불일치:{list(it.keys())}"
    assert it["reg"] and it["node"] and it["ref_law"], f"핵심 3필드 빈값:{it}"
    assert "별표" in it["ref_law"], f"ref_law 근거조항(별표) 누락:{it['ref_law']}"
    assert it["def_ref"], "def_ref(세목 정의·단서) 누락 — MED-2 부분문자열 false-positive 거름 무력화"

# UQA001(도시지역 상위코드, REG_NM 없음) → []로 거름(빈 actRegList → 직접근거0 → abstention)
def test_act_parser_empty_to_abstention():
    items = _parse_act_items(_raw("act_DTarLandUse_UQA001.json"))
    assert items == [], f"REG_NM 없는 응답을 빈 리스트로 안 거름(거짓 item 생성 위험):{items[:2]}"

def main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fail = 0
    for fn in fns:
        try: fn(); print(f"PASS {fn.__name__}")
        except Exception as e: fail += 1; print(f"FAIL {fn.__name__}: {e}")
    print("ACT_PARSER OK" if not fail else f"ACT_PARSER FAIL {fail}"); return 1 if fail else 0

if __name__ == "__main__": sys.exit(main())
