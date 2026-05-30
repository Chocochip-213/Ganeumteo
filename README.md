# 가늠터 — 건축 인허가 AI 사전진단 (풀스택 데모)

주소·용도·규모만 넣으면, 그 땅에 그 건물을 지을 수 있는지·어떤 인허가·서류가 필요한지를 **법령 원문 근거와 함께** 사전 진단한다.

## 구조
- `react_proto/` (별도 폴더) — **ReAct 에이전트(두뇌)**: gpt-5.2 + 14개 도구 + LangGraph 그래프. 본 데모가 import해서 래핑(수정 안 함, 조례 도구 1곳만 surgical).
- `infra/` — **조례 RAG**: GMS `text-embedding-3-large`(3072차원) + Postgres/pgvector(Docker).
- `backend/` — **FastAPI**가 그래프를 SSE로 래핑. `proto_bridge.py`가 두뇌로의 단일 import 경계.
- `frontend/` — **빌드툴 0**: 단일 `index.html` + vanilla ES모듈 + `EventSource`. Pretendard(self-host).
- `qa/` — 실 픽스처 캡처 + 브라우저 없는 렌더 검증.

## 실행 (Windows)
1. `cd infra && docker compose up -d`  (pgvector, 호스트 포트 5433 — 5432는 기존 컨테이너 점유)
2. (react_proto venv에서) `uv add fastapi 'uvicorn[standard]' 'psycopg[binary]' pgvector openai`
3. `react_proto/.env`에 `PG_DSN=postgresql://gameauteo:gameauteo@127.0.0.1:5433/gameauteo` 추가 (GMS_KEY는 이미 있음, gitignore)
4. 조례 인덱싱: `cd react_proto; $env:PYTHONIOENCODING='utf-8'; uv run python ..\ganeomteo\infra\build_ordinance_index.py`  (OK/SKIP/MISS 정직 로그)
5. 백엔드+프론트: `cd react_proto; uv run uvicorn app:app --app-dir ..\ganeomteo\backend --port 8000`
6. 브라우저 `http://localhost:8000`
7. (선택) 실 LLM 판정: 위를 `FORCE_STUB` 없이 실행(GMS gpt-5.2). 빠른 검증은 `$env:FORCE_STUB='1'`.

## 정직 범위 (거짓완료·과적합 금지)
- **전국 아님.** 경기 남부 14개 시군 도시계획조례 용도지역 별표만 인덱싱(243청크): 안양·광명·평택·안산·과천·남양주·군포·의왕·하남·안성·김포·광주·양평·춘천. 그 외 지자체/zone은 라이브 폴백 또는 확인필요.
- **도시계획조례만.** 건축/주차장/경관 조례는 미구현(별표 구조·에이전트 소비 로직이 별도로 필요 — 4종 지원 거짓표기 안 함). 수원·성남·용인·화성·부천·시흥·오산·여주는 도시계획조례에 해당 별표가 없어 MISS(구조 다름).
- **stub 모드 판정은 '확인필요' 고정.** 실제 멀티홉 호목해소(조례별표→건축법 시행령 별표1)는 gpt-5.2 real-LLM에서만.
- 임베딩 비대칭: 데모 규모(지자체×용도지역당 별표 1개)에선 메타필터(area_cd5/sigungu+zone)가 검색을 지배하고 3072d 벡터는 보조(동률 정렬). 경쟁 청크가 많아져야 의미검색 가치가 큼.
- pgvector 3072 > ANN 2000차원 상한 → ANN 인덱스 없음. 메타필터로 1지자체로 좁힌 뒤 정확 스캔(데모 규모 ms급, 전국은 halfvec 필요).
- 부담금 = 단가 API 없음 → 금액 안 씀(확인필요).
- 모든 픽스처는 실제 `graph.invoke` 캡처(날조 0). GMS_KEY는 코드/로그/SSE/문서 어디에도 없음(.env, gitignore).
- 기존 `research/law_fetch.py`의 평문 OC 키는 **본 작업과 무관한 기존 항목**(소유자 확인용 플래그).

## QA
- `node qa/test_frontend.mjs` — verdict 분류(전 공간+미지값)·9요소 카드 렌더(0/1/N·결측키·abstain·env null) 크래시 0.
- `cd react_proto; $env:FORCE_STUB='1'; uv run python ..\ganeomteo\qa\run_qa.py` — 실 케이스 캡처 + 구조 어설션.
- 라이브 검증: `curl` SSE 스트림 → 42 프레임(tool_call/result/citation/verdict/done) + `/diagnose/result` 9키 카드.
