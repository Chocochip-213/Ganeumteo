# -*- coding: utf-8 -*-
"""실 LLM(gpt-5.2) showcase 캡처 — Python 직접 invoke(UTF-8 깨끗, curl mojibake 우회).
양평 자연녹지 카페: RAG HIT(별표16) → 멀티홉(건축법 시행령 별표1) → 실 호목해소 verdict."""
import sys, io, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
_GAN = r"C:\Users\kmw16\Desktop\agent\probe\ganeomteo"
sys.path.insert(0, _GAN + r"\backend"); sys.path.insert(0, _GAN)
import proto_bridge as PB
from state_init import fresh_state, make_config
from langgraph.types import Command

CASES = [
    ("REAL_yangpyeong_natural", "경기도 양평군 용문면 다문리 100", "카페", 264, 1),  # 자연녹지(직접 가능)
    ("REAL_yangpyeong_resid",   "경기도 양평군 양평읍 양근리 100", "카페", 264, 1),   # 제1종일반주거(조례위임→RAG 멀티홉)
]
print("mode:", PB.MODE)
for name, addr, use, area, floors in CASES:
    st = fresh_state(addr, use, area, floors)
    tid, cfg = make_config()
    out = PB.GRAPH.invoke(st, cfg)
    guard = 0
    while PB.GRAPH.get_state(cfg).next and guard < 3:        # HITL 뜨면 알려진 값으로 resume
        guard += 1
        out = PB.GRAPH.invoke(Command(resume={"floor_area": area, "floor_count": floors, "use_type": use}), cfg)
    vals = PB.GRAPH.get_state(cfg).values
    ret = vals.get("_return")
    if not ret:
        print(f"\n[{name}] 미완(_return None) next={PB.GRAPH.get_state(cfg).next}"); continue
    c = ret["card"]; lr = c.get("legal_reasoning") or {}; cits = vals.get("citations", [])
    print(f"\n[{name}] zone={vals.get('zone')} terminal={ret['terminal_reason']} verdict={c.get('verdict')}")
    print(f"  논증={len(lr.get('steps') or [])} uijae={len(c.get('uijae') or [])} docs={len(c.get('documents') or [])} idx_hit={vals.get('doc_index_hit')}")
    print(f"  ordin={[(x.get('article'), x.get('extract_method')) for x in cits if x.get('source')=='ordin']}")
    print(f"  law={[x.get('article') for x in cits if x.get('source')=='law']}")
    print(f"  jorye={vals.get('jorye_verdicts')}")
    json.dump({"_return": ret, "citations": cits},
              open(os.path.join(_GAN, "qa", "fixtures", name + ".json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"  saved {name}.json")
