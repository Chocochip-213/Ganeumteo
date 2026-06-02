# -*- coding: utf-8 -*-
"""Live law matrix (MASTER_PLAN item 14b·§7). RUN_LIVE_LAW=1 + FORCE_STUB 해제시 실 law.go.kr fetch.
게이트 off면 SKIP(exit0) — per-commit 게이트 차단요소 아님(P0 완료 승인용 gated test)."""
import os, sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # git-bash cp949 트랩 방지
except Exception:
    pass

if os.environ.get("RUN_LIVE_LAW") != "1":
    print("test_docs_live_matrix: SKIP (RUN_LIVE_LAW≠1 — live 게이트 off). 실행: $env:FORCE_STUB=$null; $env:RUN_LIVE_LAW=1")
    sys.exit(0)
os.environ.pop("FORCE_STUB", None)   # stub 강제 해제(live)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lawlib"))
import wf_docs_agent as DOC

# (단계, 시행규칙, 조[, 항]) — 비신축 분기 포함. 실 법령 조문 전수확보 확인.
MATRIX = [
    ("건축허가", "건축법 시행규칙", "6", "①"),
    ("용도변경", "건축법 시행규칙", "12의2", None),
    ("착공신고", "건축법 시행규칙", "14", None),
    ("사용승인", "건축법 시행규칙", "16", None),
    ("농지전용", "농지법 시행규칙", "26", "②"),
]
fail = 0
for row in MATRIX:
    stage, law, art = row[0], row[1], row[2]
    hang = row[3] if len(row) > 3 else None
    try:
        r = DOC.docs_for(stage, law_name=law, article=art, hang_override=hang)
    except Exception as e:
        print(f"[{stage}] ERROR {type(e).__name__}: {e}"); fail += 1; continue
    ok = r.get("상태") == "전수확보" and r.get("건수", 0) > 0
    print(f"[{stage}] {law} 제{art}조{hang or ''} → {r.get('상태')} 건수={r.get('건수')} {r.get('사유', '')}")
    if not ok:
        fail += 1
print("DOCS_LIVE OK" if not fail else f"DOCS_LIVE FAIL {fail}")
sys.exit(1 if fail else 0)
