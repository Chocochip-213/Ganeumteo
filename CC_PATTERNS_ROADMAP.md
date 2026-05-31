# Claude Code 패턴 vs 가늠터 — 채택 로드맵 (2026-05-31 워크플로우)

7차원 정밀비교(CC 분석문서 4848줄 + 우리코드), off-the-shelf는 venv 실재확인. 8에이전트.
원본: 워크플로우 wsns06i4y. CC문서: `C:\Users\kmw16\Desktop\claude\src\agentic_study_output\CLAUDE_CODE_ANALYSIS_COMPILED.md`.

## 지금 당장 Top 5 (high/low, 대부분 내장 or 5~15줄)
| # | 할 일 | 파일 | 내장 | 효과 |
|---|---|---|---|---|
| 1 | **GraphRecursionError 캡처→graceful 종료** | sse.py·graph.py | `langgraph/errors.py:66` ✓ | recursion_limit(80) 초과 500 노출 차단 = 유일 "손밖" 크래시 봉합 |
| 2 | **도구 에러 ToolMessage에 `status='error'`** | graph.py:20,29·tools.py:579 | `langchain_core/messages/tool.py:82` ✓ | sse가 문자열스니핑 없이 에러턴 1급식별 |
| 3 | **MemorySaver→SqliteSaver** | graph.py:264 | ★`uv add langgraph-checkpoint-sqlite` 선행 | 서버 재시작/크래시/배포시 진행중 진단 증발 차단 = **데모 생존** |
| 4 | **_fit_context 압축 관측 로그(5줄)** | agent.py:127 | 없음(계측) | 압축 도는지·90만 닿는지 지표 0 → 튜닝근거 |
| 5 | **step_exhausted 종료사유 1급화** | graph.py:91,214 | 없음(라벨) | 캡도달이 abstention 문자열에 묻힘 → 1급 |

→ #1+#5(종료라벨)·#2(같은함수)는 graph.py+sse.py 한 묶음.

## ★ 너가 원하던 "삭제 말고 요약" = 내장 있음
**D2. `SummarizationMiddleware`** (`.venv/.../langchain/agents/middleware/summarization.py:182`) = CC autocompact(Layer5) LLM요약. trigger=('fraction',0.9)·keep=('messages',12)·`_find_safe_cutoff_point`가 AI/Tool 쌍 보존(orphan 방지)·summary_prompt 커스텀(→'인용·verdict 보존' 지침). _fit_context(clear=Layer1) 뒤단 안전망으로. med/med. **1M이라 빈도 낮지만 안전망 0→확보.**

## 이미 잘함 (건드리지 마)
clear(keep=3)=CC microcompact 동형 · state full+요청만trim=contextCollapse철학 · terminal_reason+_STATUS=12-reason 분류 · _wrap_tool_call 에러격리+GraphBubbleUp보존 · 법적판단 fail-closed · thread_id=sessionID 재개3종 · interrupt 자유round-trip · SSE 정규화스키마 · 단일StateGraph(과설계회피 정답).

## 차원별 권고 (Top5 외)
- **영속**: A2 dangling tool_call repair(med/low, app.py:57 followup)·A3 재개thread목록 라우트(med/med, checkpointer.list).
- **종료**: B3 terminal_reason Literal enum+status 단일출처(med/low).
- **도구**: C2 매직넘버 슬라이스→단일 `_MAX_BODY` 상수(med/low)·C3 외부API 공통 retry 래퍼(med/med, 일시장애를 abstention 전 흡수; `tool_retry.py ToolRetryMiddleware` 패턴).
- **스트리밍**: E1 최종답변만 토큰 스트리밍(high/med, astream stream_mode=['updates','messages'])·E2 노드'시작'이벤트(med/low, tasks모드/get_stream_writer)·E3 Tombstone 등가 프론트만(med/low)·E4 SSE seq→`id:`(low/low).
- **subagent**: F1 별표멀티홉만 격리실행+요약반환(med/med, create_agent+Summarization, 측정후)·F2 적대검증노드 고위험verdict한정(med/med).

## MVP 제외 (지금 만들지 마 — 트리거만 기록)
1. 실행前 deny 권한게이트(CC 10단) — 18툴 전부 read-only, 차단할 파괴동작 0. 프롬프트 1줄만.
2. PostgresSaver+멀티워커 — 멀티유저 결정 후. ★미설치.
3. 멀티에이전트(coordinator/worktree) — 직렬단일도메인 fan-out 이득 0.
4. tool_result disk-persist 풀구현 — C2로 대체.
5. HumanInTheLoopMiddleware per-tool — 쓰기도구 0개. 비가역도구 추가시.
6. HumanInterrupt 표준스키마 — 자작도 작동. 다사용자+Studio붙일때.
7. audit log·thread TTL — A1과 묶어 다사용자 전환시.

## ★ 사실 정정 3건
1. HumanInterrupt 경로 = `from langgraph.prebuilt.interrupt import HumanInterrupt`(langchain.agents.interrupt 미존재).
2. sqlite/postgres saver **미설치** — A1 전 `uv add langgraph-checkpoint-sqlite` 필수.
3. limit 미들웨어 파라미터 = `thread_limit`/`run_limit`(max 아님).
