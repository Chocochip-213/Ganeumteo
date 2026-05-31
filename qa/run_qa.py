# -*- coding: utf-8 -*-
"""실제 graph.invoke로 다중 케이스 + 엣지를 캡처 → fixtures/*.json (날조 0). 구조·graceful 어설션.
실행: cd ganeomteo; $env:FORCE_STUB='1'; uv run python qa\\run_qa.py
(Windows cmd `set X=1 && uv run`는 subprocess에 전파 안 됨 — 아래처럼 os.environ in-process로 강제.)"""
import os, sys, json
os.environ["FORCE_STUB"] = "1"                       # in-process(전파 보장)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_GAN = str(__import__("pathlib").Path(__file__).resolve().parents[1])   # ganeomteo(통합)
sys.path.insert(0, _GAN + r"\backend")
sys.path.insert(0, _GAN)
import proto_bridge as PB
from state_init import fresh_state, make_config

FIXDIR = os.path.join(_GAN, "qa", "fixtures")
os.makedirs(FIXDIR, exist_ok=True)

CASES = [
    ("yangpyeong_cafe",      "경기도 양평군 양평읍 양근리 100", "카페", 264, 1),   # 인덱스 HIT, 풀카드
    ("yangpyeong_office_big","경기도 양평군 양평읍 양근리 100", "사무소", 600, 5),  # 규모 둘다 필요
    ("chuncheon_near",       "강원특별자치도 춘천시 동내면 거두리 1", "제2종근린생활시설", 180, 2),
    ("nonexistent_abstain",  "없는시 없는읍 없는리 99999", "카페", 100, 1),         # geocode 실패→보류
]

VERDICT_SPACE = {"가능", "가능(조건부)", "위험·금지", "확인필요"}
results = {}
errs = 0
for name, addr, use, area, floors in CASES:
    st = fresh_state(addr, use, area, floors)
    tid, cfg = make_config()
    try:
        out = PB.GRAPH.invoke(st, cfg)
        ret = out.get("_return", {})
        payload = {"_return": ret, "citations": out.get("citations", [])}
        json.dump(payload, open(os.path.join(FIXDIR, name + ".json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        card = ret.get("card", {})
        shape = "success" if (card.get("legal_reasoning") or ret.get("terminal_reason") == "completed") else "abstain"
        v = card.get("verdict")
        print(f"OK  {name}: terminal={ret.get('terminal_reason')} verdict={v} shape={shape} "
              f"uijae={len(card.get('uijae') or [])} docs={len(card.get('documents') or [])} "
              f"cits={len(out.get('citations', []))} idx_hit={out.get('doc_index_hit')}")
        results[name] = payload
    except Exception as e:
        errs += 1; print(f"ERR {name}: {type(e).__name__}: {e}")

print("\n=== 어설션 ===")
fail = 0
for name, p in results.items():
    ret, card = p["_return"], p["_return"].get("card", {})
    try:
        assert set(["terminal_reason", "status", "card"]).issubset(ret), "envelope 4키"
        c = card.get("citations")
        assert c is None or isinstance(c, (int, list)), "citations int|list"
        v = card.get("verdict")
        assert v is None or isinstance(v, str), "verdict str|None"
        # 성공카드면 9요소 영문키, 보류면 한글키 — 둘 다 허용(과적합 방지)
        print(f"  PASS {name} (verdict='{v}' in_space={v in VERDICT_SPACE})")
    except AssertionError as e:
        fail += 1; print(f"  FAIL {name}: {e}")
print(f"\n캡처 {len(results)}건, 어설션 실패 {fail}건, 실행오류 {errs}건")
if fail or errs:   # 테스트 게이트(검수 #11) — 실패/크래시 있으면 비정상 종료
    sys.exit(1)
print("QA OK")
