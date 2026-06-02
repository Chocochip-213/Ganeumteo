# 가늠터 (Ganeumteo)

> **건축 인허가 AI 사전진단 에이전트** — 주소와 용도만 입력하면, 그 땅·건물에 원하는 건축행위가 가능한지 LangGraph 기반 ReAct 에이전트가 공공 데이터를 라이브로 조회해 근거와 함께 종합 진단합니다.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-ReAct-1C3C3C)
![FastAPI](https://img.shields.io/badge/FastAPI-SSE-009688?logo=fastapi&logoColor=white)
![무하드코딩](https://img.shields.io/badge/무하드코딩-근거계약-success)

---

## 무엇인가

빈 땅에 카페를 신축할 수 있는지, 기존 건물 한 층을 학원·헬스장으로 용도변경할 수 있는지 — 일반인이 건축사 상담 전에 스스로 가늠해볼 수 있도록 **입지·행위제한·조례·의제(함께 처리되는 인허가)·인허가 절차·제출서류·규모상한·작성주체**를 한 번에 진단합니다.

- **입력**: 주소 + 무엇을(용도) + 어떻게(신축/용도변경/대수선 등)
- **출력**: 4등급 종합판정(가능 / 가능(조건부) / 위험·금지 / 확인필요) + **근거 인용** + 인허가 절차 타임라인 + 단계별 제출서류 + 규제효과·부담금 가늠

> **이 저장소의 1차 산출물은 에이전트입니다.** FastAPI 서버·바닐라 JS 프론트는 그 에이전트를 감싼 한 가지 어댑터일 뿐입니다. 그래프(`agent/`)는 다른 백엔드·서비스에서 그대로 호출할 수 있도록 설계돼 있습니다([에이전트 통합](#에이전트-통합-다른-백엔드--서비스-연동) 참고).

## 핵심 설계 — 무하드코딩 + 근거계약

두 가지 불변식이 전 코드를 관통합니다.

### 1. 무하드코딩 — 코드는 의미를 판단하지 않는다
케이스별 분기, 서류명, 요율, 가부 판정을 **코드에 박지 않습니다.** 의미 판단(용도 분류·가부·시설 해당성·절차 순서)은 **전부 LLM**이 내리고, 코드는 **라우팅·형식 파싱·집계·결정적 법공식상수(예: 에너지절약계획서 500㎡, 1평=3.3058㎡)·fail-closed 안전판정**만 담당합니다. 특정 주소·업종·시설명으로 `if` 분기하지 않습니다(회귀는 일반 불변식 테스트로 잡습니다).

### 2. 근거계약 — 모든 결론은 실재하는 근거에 묶인다 (＂확인필요 떠넘기기＂ 박멸)
이 프로젝트의 핵심 가치는 **AI가 스스로 조사할 수 있는 걸 사용자에게 ＂직접 확인하세요＂로 떠넘기지 않는 것**입니다.

- 모든 결론성 도구(`record_*`)는 **`basis_claims`**(근거계약)를 동반해야 커밋됩니다 — `{ field_path(어느 결론 필드 지지), claim_type(factual_input·legal_applicability·calculation_basis·authority_discretion), evidence_id(state에 실재하는 fetch 근거), quote_or_span(원문 실재) }`.
- **코드는 구조만 검증**합니다: evidence_id가 state에 실재하는가 · quote가 원문(`EvidenceRecord`)에 실재하는가 · claim_type×근거종류 허용 관계인가. **＂이 근거가 정말 이 결론을 받치는가＂(논리적 지지)는 LLM의 책임**입니다. 코드가 그걸 판정하면 곧 하드코딩이기 때문입니다.
- **bare 확인필요 금지**: `확인필요`로 둘 땐 반드시 `unresolved_by`로 분류해야 합니다 — `agent`(더 조사하면 풀림 → **완료 금지, 도구 루프로 재조사**) · `user`(사용자만 아는 사실) · `authority`(관할 심의/재량, 그 재량임을 말하는 법령근거 동반) · `data_unavailable`(데이터원 부재) · `tool_budget_exhausted`(조사 한도 소진). **최종 카드에 `agent` 미해결은 남지 못합니다.**
- `근거확보`(조문을 찾음) ≠ `완료`(이 케이스 영향판정). 완료는 LLM이 `record_*`로 커밋해야 합니다.

## 아키텍처 (agent-first)

```
                ┌──────────────────────────────────────────────┐
   입력(주소·용도) │   agent/  ── LangGraph ReAct 그래프 (핵심) ──   │
   ───────────►  │                                              │
                │   agent ⇄ tools  (geocode·get_land_use·       │
                │      act_landuse·law_fetch·record_*… )         │
                │        │                                       │
                │   completeness_guard ─ 미충족시 재조사 바운스      │
                │        │      (per-overlap 규제 완료게이트·       │
                │        │       agent 미해결 루프백·절차판정)       │
                │   build_reasoning ─ fail-closed 안전게이트       │
                │        │      (근거 미확보·맹지·잘린 별표 → 강등)   │
                │   compose ─► 진단 카드(아래 출력 계약)            │
                └───────────────────┬──────────────────────────┘
                                    │ GRAPH.invoke(state, config) → card
            ┌───────────────────────┼───────────────────────┐
       backend/ (FastAPI+SSE)   당신의 백엔드          배치/CLI
       프론트 same-origin 서빙   (REST/gRPC/큐…)      (run.py)
```

- **`agent/graph.py`** = 단일 진실원. `build_graph()`가 컴파일된 LangGraph 그래프(`GRAPH`)를 반환합니다. 체크포인터는 `SqliteSaver`(실 LLM=파일 영속 / stub=in-memory).
- **`backend/app.py`** = SSE 어댑터 하나일 뿐. 그래프를 직접 쓰면 SSE 없이도 됩니다.
- **모델**: `LLM_BASE_URL`(.env, OpenAI 호환 프록시) → 없으면 결정적 stub-planner(테스트용).

## 데이터 소스 (전부 라이브 fetch)

| 소스 | 용도 |
|---|---|
| **VWorld** | 주소→좌표, 지적(지목·도로접면), 용도지역·규제중첩(reg_overlaps), 공시지가 |
| **data.go.kr (1613000 / 건축HUB)** | 행위제한(토지이용), 건축물대장 표제부·층별개요 |
| **law.go.kr (DRF)** | 법령·자치법규 원문, 별표(행위제한·주차·부담금·별표1 용도분류), 별지서식 다운로드 |

모든 fetch 결과는 `EvidenceRecord`로 적재되어 근거계약 검증(quote 실재)에 쓰입니다.

## 설치 & 실행

[uv](https://docs.astral.sh/uv/) 권장.

```bash
uv sync                                   # 1) 의존성
cp .env.example .env                      # 2) 키 채우기(VWORLD_KEY·DATAGO_KEY·LAW_OC·KAKAO_KEY·LLM_BASE_URL)
uv run uvicorn app:app --app-dir backend --port 8000   # 3) 서버(프론트 same-origin)
```

브라우저 http://127.0.0.1:8000 . 빠른 검증은 `FORCE_STUB=1`(결정적 stub 경로 — 키·LLM 불필요).

> 모든 API 키는 `.env`(gitignored)에만. 코드·커밋에 노출 금지.

## 에이전트 통합 (다른 백엔드 / 서비스 연동)

에이전트는 FastAPI에 묶여 있지 않습니다. 어떤 파이썬 백엔드(REST·gRPC·메시지 큐·배치)에서도 그래프를 직접 호출하세요.

```python
import sys; sys.path[:0] = ["agent", "lawlib", "backend"]   # 또는 패키지 경로 설정
from proto_bridge import GRAPH                # 컴파일된 LangGraph 그래프
from state_init import fresh_state, make_config

state = fresh_state(address="서울특별시 ...", use_type="카페",
                    floor_area=264, floor_count=1)
tid, cfg = make_config()                      # 128-bit opaque thread_id + recursion_limit
out = GRAPH.invoke(state, cfg)                 # 동기 1회 진단
card = out["_return"]["card"]                  # 진단 카드(아래 출력 계약)

# 스트리밍(노드별 진행)은 GRAPH.stream(state, cfg) / 또는 backend/sse.py 참고.
# 사람 확인이 필요하면(HITL) interrupt가 발생 → Command(resume={...})로 재개.
```

연동 시 알아둘 계약:

- **입력 계약**: `fresh_state(address, use_type, floor_area?, floor_count?)` → `GaneomteoState`(TypedDict). 누적 필드는 reducer로 병합되므로 직접 만들 땐 `state_init`를 쓰세요.
- **세션/멀티턴**: 같은 `thread_id`로 `make_config`하면 SqliteSaver가 직전 상태를 이어받습니다(후속 질문·resume). 진단마다 **새 thread_id**를 쓰면 run 혼입이 없습니다.
- **결정성/테스트**: `FORCE_STUB=1`이면 LLM 없이 결정적 경로(스키마·배관 검증용). 실 판정 품질은 LLM 모드에서만.
- **무상태 REST 래퍼**라면: `make_config(client_thread_id)`로 thread를 복원해 `invoke`/`stream` 후 `out["_return"]`를 반환하면 됩니다.

## 진단 카드 출력 계약 (`out["_return"]`)

```jsonc
{
  "terminal_reason": "completed",     // completed | tool_budget_exhausted | need_human | no_grounds | …
  "status": "완료",                    // terminal_reason의 한국어 라벨(완료/부분완료/사람검토…)
  "card": {
    "verdict": "확인필요",             // 가능 | 가능(조건부) | 위험·금지 | 확인필요
    "verdict_labels": [               // LLM이 고른 판정 축들(고정 목록 아님)
      { "dimension": "용도", "status": "충족|주의|확인필요|불가",
        "blocking_level": "none|critical",
        "unresolved_by": "none|agent|user|authority|data_unavailable|tool_budget_exhausted",
        "basis_claims": [ /* 근거계약 */ ], "reason": "…" }
    ],
    "landuse_resolution": { "status": "가능|불가|조건필요|확인필요", "intended_use": "…",
                            "matched_node_desc": "…", "mismatch_reason": "…" },
    "procedure_steps": [              // 인허가 절차 타임라인(documents와 분리)
      { "step_id": "building_permit", "order": 0, "stage_key": "건축허가",
        "applies": "yes|no|unknown", "status": "근거확보|확인필요",
        "unresolved_by": "…", "actor": "…", "authority": "…",
        "law_name": "…", "article": "…", "requires_documents": true,
        "related_document_stage_keys": ["건축허가"], "basis_claims": [ … ] }
    ],
    "documents": [                    // 제출서류(절차와 분리). list_status=목록확보 ↔ items[].applies_status=해당여부
      { "stage": "건축허가", "list_status": "전수확보|확인필요", "law": "…", "article": "…",
        "count": 12, "items": [ { "ho": "1.", "doc_name": "…", "applies_status": "해당|비해당|확인필요" } ] }
    ],
    "reg_effects": [ { "reg_name": "…", "status": "해소|미해소|해당없음|확인필요",
                      "resolution_committed": true, "blocking_level": "critical|normal|reference",
                      "unresolved_by": "…" } ],
    "uijae": [ … ], "scale_limits": { … }, "levies": [ … ], "parking_req": { … },
    "term_notes": { … }, "citations": 5, "abstentions": [ … ]
  }
}
```

전체 `evidence_records`(원문 store)는 `out["evidence_records"]`(state)에 있습니다 — 근거ID→원문 매핑.

## 도구 · 근거계약

LLM이 결론을 커밋하는 **결론성 도구**(전부 `InjectedState`로 근거 실재 검증):

| 도구 | 커밋하는 결론 |
|---|---|
| `record_use_classification` | 생활어(카페·피시방) → 건축법 시행령 별표1 canonical 세목(act_landuse 선결) |
| `record_landuse_resolution` | 행위제한 가부(NODE_DESC↔의도용도 일치 확인 후) — 코드 승격 대체 |
| `record_work_type` | 신축/용도변경/대수선/증축/해체(맹지·절차 게이트가 읽는 단일원) |
| `record_reg_resolution` | 중첩규제·보호구역 영향판정(일반 resolver 패턴 — 업종/구역 분기 없음) |
| `record_ordinance_ruling` | 조례 별표 호목 해소 결론 |
| `record_procedure_steps` | 인허가 절차 타임라인 |
| `record_verdict` | 최종 종합판정(차단 축 위 '가능' 금지) |
| `assess_conditional_docs` | 조건부 서류 해당/비해당(비해당은 근거 필수) |

계산 도구(`parking_quota`·`levy_estimate`)도 율·기준면적 값에 `evidence_id`를 요구합니다. 법정 결정상수는 `StaticEvidenceRecord` provenance(어느 법조·기준)를 부착합니다.

## 테스트 & 품질 게이트

```powershell
# per-commit (stub 구조 회귀 — exit 0)
uv run python -m compileall agent backend lawlib qa
uv run python backend\_regress.py        # stub e2e → completed·카드 구조
uv run python backend\_verify_docs.py     # 문서 list_status·applies_status·evidence_id 계약
uv run python qa\test_boundary.py         # 모듈·도구 계약·InjectedState·코드분기 0
uv run python qa\test_golden.py           # 근거계약 일반 불변식(허위 evidence·bare 확인필요·세목 불일치 positive 거부)

# P0 완료 승인 (live, gated — 키 필요)
$env:FORCE_STUB=$null; $env:RUN_LIVE_LAW=1; uv run python qa\test_docs_live_matrix.py
$env:FORCE_STUB=$null; $env:RUN_LIVE_LLM=1; uv run python qa\test_workflow_live_matrix.py
```

`qa/test_golden.py`는 특정 케이스가 아니라 **일반 불변식**을 검증합니다(과적합 방지). 발견된 버그는 코드 분기가 아니라 불변식 + regression fixture로 잡습니다.

## 프로젝트 구조

```
agent/      ★ LangGraph 그래프 · 도구(record_*) · 상태/근거계약 모델 · 시스템 프롬프트  ← 핵심
backend/    FastAPI(SSE) 어댑터 · 상태 초기화 · 회귀 게이트
lawlib/     법령/공간 fetch · 서류·규제 라우팅(prototype run()은 운영 경로 아님)
frontend/   진단 UI(바닐라 JS) · 절차 타임라인·서류 카드 렌더
infra/      자치법규 RAG 인덱스(선택, pgvector)
qa/         구조 회귀 · golden 불변식 · live smoke harness
```

## 정직 범위 (한계)

- **조례 RAG는 전국이 아님** — 일부 시군 도시계획조례 별표만 사전 인덱싱. 그 외는 라이브 폴백 또는 `확인필요`.
- **부담금 단가 데이터원 없음** — 단가 출처가 없으면 금액 미산출 `확인필요`.
- **교육환경 등 일부 보호구역 탐지** — 학교 geofence 등 공간 데이터 미배선분은 reg_overlaps에 안 들어오면 진단에서 빠질 수 있음(들어오면 일반 resolver가 처리).
- **stub 모드는 보수적** — `FORCE_STUB`는 결정적 스캐폴드. 멀티홉 해소·다차원 판정은 LLM 모드에서만.
- 본 결과는 **사전 가늠**이며 법적 효력이 없습니다. 실제 인허가는 관할 행정청·건축사 검토가 필요합니다.

## 라이선스

미정(사내/연구용). 사용 전 문의.
