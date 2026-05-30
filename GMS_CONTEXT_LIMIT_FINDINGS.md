# GMS 요청 크기 한도 — 진단·수정·결정 기록 (2026-05-31)

## 1. 증상
긴 진단(별표·조례 원문, docs 결과 누적) 후 에이전트가 죽음:
```
[agent] 자동판정 보류
LLM 예외 BadRequestError: 400 - {'message':'[GMS 에러] Model not found in request for domain api.openai.com'}
[completeness_guard] 미충족 ['조건부판정:17건'](스텝 캡)   # ← LLM 죽어서 생긴 2차증상
```

## 2. 근본원인 — 통제실험으로 확정
**GMS 프록시 게이트웨이의 요청 body 크기 한도(~40KB).** OpenAI 본체 아님.
- 같은 model(gpt-5.2)·올바른 param(`max_completion_tokens`) 고정, **body 크기만** 변화:
  | body | 결과 |
  |---|---|
  | ~0KB | 200 OK |
  | ~56KB | 400 `[GMS] Model not found in request` |
  | ~84KB | 400 동일 |
  크기가 유일 변수 = 원인 확정. GMS 게이트웨이가 큰 body 파싱 못 해 model 필드를 못 찾는 것(에러문구가 오해 소지).

### 헷갈리기 쉬운 두 가지(정정)
- **`max_tokens` 에러는 무관**: 수동 curl이 `max_tokens` 넣어 난 `[OpenAI 에러]`. 에이전트는 LangChain 1.2.2라 `max_completion_tokens` 자동 전송 → 그 에러 안 남.
- **GMS 로그에 크기실패가 안 보이는 이유**: 크기초과 = `[GMS 에러]`(게이트웨이 차단, OpenAI 미도달) → OpenAI 사용량 로그에 안 남음. `[OpenAI 에러]`인 max_tokens만 로그에 남아서 "실패는 그것뿐"으로 보임.

## 3. 핵심 결론 — 이건 GMS만의 문제
- 직접 OpenAI/Anthropic 키 쓰면 **body 크기 한도 없음**. 한계는 모델 컨텍스트(200K~1M 토큰)뿐.
- 진단 1건 full(별표·조례 원문 다 포함) ≈ **20~30K 토큰** → 200K의 1/8. **여유.**
- ⇒ **컨텍스트 관리(삭제/요약) 자체가 GMS ~40KB 한도 때문에 짜낸 우회책.** 직접 키면 불필요(full 전송).

## 4. 현재 수정 (커밋 48cae82 → dea3695)
LangChain 내장 **`ClearToolUsesEdit`**(Anthropic `clear_tool_uses_20250919` 미러) 채택:
- 토큰 trigger(6000) 초과 시 오래된 도구결과를 `[cleared]`로 비움, 최근 keep(3)개 보존. 토큰기반·idempotent.
- **state엔 full 유지(렌더·citation), LLM 요청에만 적용**(model_copy, 원본 비파괴). 검증: 21466→4966 tok, invoke 200 OK.
- + LLM 예외시 `terminal_reason='llm_error'` → route 즉시 abstain(불필요 가드 바운스 차단), status='재시도필요'.

### Claude Code 실제 compaction = 5단 (참고; 우리는 ①만)
`query.ts:379-535`: ① **budget**(`applyToolResultBudget`=도구결과 비우기/자르기) → ②snip(ant-only) → ③microcompact → ④collapse(ant-only) → ⑤ **autocompact = 풀 LLM 요약**(최후수단, 13k 버퍼). 메모리 스캔은 Sonnet.
- 우리 `ClearToolUsesEdit` = **①단(clear)** 에 해당. ⑤(LLM요약)은 미구현.

## 5. 미결정 — 사용자 선택 대기
사용자 입장: **"삭제하면 안 된다"**(의제손실 싫음, 요약 원함). 단 아래 갈림:

| | A) GMS 유지 | B) 직접 API 키 |
|---|---|---|
| 40KB 한도 | 있음 → 우회 필요 | **없음** |
| 컨텍스트 관리 | clear(현재) 또는 **gpt-5-mini 요약** | **불필요**(full 전송) |
| 비용 | 무료(SSAFY) | 유료 |

### A를 택하면(GMS 강제) — 요약 구현 주의
- **순환문제**: 큰 블록을 한 번에 요약하려면 그 요약요청 자체가 40KB 초과 → 불가. → **결과 하나씩 개별 요약**(각 ≤한도) + 캐시해야 함. 결과당 LLM 1콜(누적 지연).
- **GMS 가용 작은모델 확인됨**: `gpt-5-mini` 200 OK, `gpt-4o-mini` 200 OK. (`gpt-5.2-mini`/`gpt-5.2-nano`=없음.) → 요약은 gpt-5-mini로 싸게.
- 대안(무LLM): 에이전트가 record_*로 **결론을 이미 state·kept컨텍스트에 기록** → 오래된 원문 자리에 "[별표1 조회·해소 완료, 결론 기록됨]" 식 정보성 placeholder(요약 아님, 무비용).

### B를 택하면(직접 키)
우회 전부 제거: `_fit_context` trigger 대폭 상향 or 제거, full 컨텍스트 전송. 가장 깨끗.

## 6. 결정 후 할 일
- A-요약: `_fit_context`를 per-result lazy 요약(gpt-5-mini)+캐시로 교체, 실패시 placeholder 폴백.
- A-placeholder: `ClearToolUsesEdit.placeholder`를 정보성 문구로(현재 '[cleared]').
- B: trigger 상향/제거.
- (공통 미완) 프런트 llm_error시 '다시하기' 버튼(백엔드 status='재시도필요'는 이미 줌).

## 환경
- 가용 키: GMS_KEY만(ANTHROPIC/OPENAI 직접키 없음). → B 가려면 키 발급 필요.
- 실행: `cd ganeomteo; uv run uvicorn app:app --app-dir backend --port 8000`.
