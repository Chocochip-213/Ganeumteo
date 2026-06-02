# -*- coding: utf-8 -*-
"""Live workflow matrix (MASTER_PLAN item 14b·§7). RUN_LIVE_LLM=1 + FORCE_STUB 해제시 실 LLM e2e 진단.
새 도구계약(use_classification→landuse_resolution·work_type·procedure_steps·basis_claims·unresolved_by)으로
진단이 도는지 + P0 완료기준(bare 확인필요 0·procedure_steps 존재·근거계약) smoke.
게이트 off면 SKIP(exit0) — 실 LLM 키/네트워크 필요라 per-commit 게이트 아님."""
import os, sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # git-bash cp949 트랩 방지
except Exception:
    pass

if os.environ.get("RUN_LIVE_LLM") != "1":
    print("test_workflow_live_matrix: SKIP (RUN_LIVE_LLM≠1). 실행: $env:FORCE_STUB=$null; $env:RUN_LIVE_LLM=1 (LLM_BASE_URL/키 필요)")
    sys.exit(0)
os.environ.pop("FORCE_STUB", None)   # stub 강제 해제 → 실 LLM agent
os.environ.pop("APP_MODE", None)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in ("agent", "lawlib", "backend"):
    sys.path.insert(0, os.path.join(_ROOT, p))
import proto_bridge as PB
from state_init import fresh_state, make_config

# 분기 다양성(신축·비신축·보호구역 등) — 실 LLM이 새 계약으로 처리하는지. 주소는 운영 데모용 샘플.
CASES = [
    ("경기도 양평군 양평읍 양근리 100", "카페", 264, 1),
]
fail = 0
for addr, use, fa, fc in CASES:
    try:
        out = PB.GRAPH.invoke(fresh_state(addr, use, fa, fc), make_config()[1])
    except Exception as e:
        print(f"[{addr} {use}] ERROR {type(e).__name__}: {e}"); fail += 1; continue
    card = out["_return"]["card"]
    verdict = card.get("verdict")
    procs = card.get("procedure_steps", [])
    # P0 완료기준 smoke
    bad = []
    if "procedure_steps" not in card:
        bad.append("procedure_steps 부재")
    if verdict not in ("가능", "가능(조건부)", "위험·금지", "확인필요"):
        bad.append(f"VERDICT_SPACE 위반:{verdict}")
    for v in (card.get("verdict_labels") or []):
        if v.get("status") == "확인필요" and v.get("unresolved_by", "none") == "none":
            bad.append(f"bare 확인필요 축:{v.get('dimension')}")
    print(f"[{addr} {use}] verdict={verdict} procedure={len(procs)} labels={len(card.get('verdict_labels', []))} {'· '+'; '.join(bad) if bad else 'OK'}")
    if bad:
        fail += 1
print("WORKFLOW_LIVE OK" if not fail else f"WORKFLOW_LIVE FAIL {fail}")
sys.exit(1 if fail else 0)
