# -*- coding: utf-8 -*-
"""react_proto LangGraph로의 단일 import 경계. 그래프 1회 빌드(SqliteSaver 파일 영속 체크포인터; stub은 in-memory).
검수 fix#4: sys.path에 ganeomteo도 넣어 react_proto/tools.py의 `import infra.ordin_rag` 동작 + RAG 임포트 스모크(죽은 RAG 가시화)."""
import sys
from pathlib import Path

_GAN = Path(__file__).resolve().parents[1]   # ganeomteo/ (단일 홈)
for _p in (_GAN, _GAN / "lawlib", _GAN / "agent"):   # infra.ordin_rag / law_fetch·wf_* / graph·tools·state·agent
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

# RAG 임포트 스모크 — 실패하면 조용히 죽지 않고 경고(검수 fix#4)
try:
    from infra.ordin_rag import lookup_ordin  # noqa: F401
    RAG_OK = True
except Exception as _e:
    RAG_OK = False
    print(f"[proto_bridge] WARN infra.ordin_rag 임포트 실패 → RAG 비활성(live fallback): {_e}", file=sys.stderr)

from graph import build_graph

GRAPH, MODE = build_graph()
print(f"[proto_bridge] graph 빌드 완료 mode={MODE} rag_import={'OK' if RAG_OK else 'DEAD'}", file=sys.stderr)
