# 가늠터 풀스택 데모 — BUILD PLAN (검수 반영본)

> 워크플로우 15에이전트 설계+심사+적대적검수 산출. 승자=vanilla JS 제로빌드 + FastAPI + pgvector RAG.
> **규율: 과적합 금지(100% 데이터주도) · 거짓완료 금지(데모범위 정직) · 날조 금지(픽스처=실제 캡처) · 단순 우선(karpathy).**
> 본 문서 = 단일 진실원. 아래 "검수 FIX" 전부 구현에 접음.

## 아키텍처
- **백엔드**: FastAPI가 기존 `react_proto`(LangGraph gpt-5.2 ReAct) **무수정 래핑**(조례 도구 1곳만 surgical). `graph.stream(stream_mode="updates")`를 워커스레드→async큐로 SSE. **`astream_events` 금지**(GMS gpt-5.2서 tool_call_id=None ValidationError, trace.py:3 실측).
- **RAG**: 임베딩 `text-embedding-3-large`(GMS, 3072d, openai SDK). 벡터DB `pgvector/pgvector:pg16`(Docker, 호스트 5433). **3072>2000 → ANN 인덱스 불가**, 메타필터(area_cd5)→정확스캔.
- **프론트**: 빌드툴 0. 단일 `index.html` + vanilla ES모듈 + `EventSource`. FastAPI가 same-origin 정적서빙. **Pretendard**(self-host woff2).
- **데이터 흐름**: 입력폼 → `/diagnose/stream`(SSE 트레이스) → `done` → `/diagnose/result`(ReturnEnvelope 4키) → 9요소 카드.

## 데이터 계약 (과적합 방지 핵심)
- **SSE TraceEvent**: `{seq, kind, node, label, detail, ts_seq}`. kind∈{node_enter,tool_call,tool_result,node_done,thinking,citation,verdict,interrupt,abstain,error,done}. UI는 **모르는 kind 무시**. 병렬 tool_calls는 seq 공유→`(tool,args)`로 dedup.
- **ReturnEnvelope**(`graph.py finalize`) = **정확히 4키** `{terminal_reason, status, card, abstentions}`.
- **card 이중 형태(필수 분기)**:
  - **성공카드**(compose, 영문키, `legal_reasoning` 존재 OR `terminal_reason==completed`): `{verdict(오픈문자열), legal_reasoning{steps[]}, uijae[], documents[{stage,count,status}], scale_limits{}, author{}, reg_effects[], citations(INT), abstentions[]}`.
  - **기권카드**(abstain, 한글키): `{verdict:'확인필요', terminal, 사유, 입지{지목,용도지역,도로접면}, citations(int)}`. 영문 9키 없음.
  - → card.js는 `legal_reasoning 존재/terminal==completed`로 분기 + **양쪽 키 방어적 읽기**.
- **verdict = 오픈 문자열**. 값공간 `{가능, 가능(조건부), 위험·금지, 확인필요}`지만 **enum switch 금지** → `classifyVerdict`(prefix/substring), 모르는 값→raw+neutral. `위험·금지`=U+00B7 가운뎃점 보존, 한 칩.
- **roadmap·pitfalls·levies = 프로토 카드키 없음** → roadmap=documents+uijae 순서 합성, pitfalls=has_proviso+_delegated+scale불린+abstentions 합성, levies='단가 미제공→확인필요'(금액 절대 안 씀).
- **citations(card)=INT 카운트**(graph.py:117), 실제 Citation 객체는 `state.citations`/`legal_reasoning.steps[].basis`. UI int|list coerce.
- **vworld basis = 데이터지 법적근거 아님**(graph.py:53 substantive=law/ordin/data만). UI는 vworld를 muted '입지 출처'로, '근거 N건'에 안 셈.

## 파일 트리
```
ganeomteo/
  BUILD_PLAN.md          (이 문서)
  README.md              실행순서·정직범위·엣지목록
  __init__.py            (네임스페이스 명확화)
  infra/
    __init__.py
    docker-compose.yml   pgvector:pg16, 5433:5432, gameauteo creds(로컬,비밀아님)
    schema.sql           ordin_chunk(vector(3072)), area_cd5 키, NO ANN, GIN(body_tsv)
    embed.py             GMS text-embedding-3-large 클라(batch+retry, dim=3072 assert)
    db.py                psycopg conn + idempotent upsert
    build_ordinance_index.py  빌드인덱서(도시계획만, area_cd5 키, utf-8 reconfigure)
    ordin_rag.py         런타임 lookup(zone-None guard, area_cd5, ordin_kind, 127.0.0.1)
  backend/
    __init__.py
    proto_bridge.py      sys.path += react_proto,research,**ganeomteo** + 그래프 1회 빌드 + RAG import smoke
    state_init.py        입력→초기 State(누적필드 pre-init) + config(server thread_id)
    labels.py            node/tool→한글 라벨(unknown→generic)
    sse.py               graph.stream→TraceEvent 정규화(structural found, _safe_delta quote≤110)
    app.py               3 엔드포인트 + StaticFiles(same-origin)
  frontend/
    index.html           단일 페이지, Pretendard @font-face
    theme.css            미감 SSOT(지적도 모노크롬+1액센트, non-slop)
    verdict.js           classifyVerdict(오픈문자열 — #1 과적합가드)
    card.js              이중카드 분기 + 9요소 제너릭 렌더
    trace.js             11 SSE kind + unknown무시 + (tool,args)dedup
    app.js              폼→EventSource→dispatch + HITL
    fonts/               Pretendard*.woff2 (self-host)
  qa/
    run_qa.py            멀티케이스+엣지, 실제 캡처 → fixtures/*.json
    fixtures/            실제 graph.invoke 캡처(날조0)
```

## 검수 FIX (전부 구현에 접음)
**HIGH**
1. **zone=None 임베딩 오염**: `lookup_ordin`서 `if not zone or not str(zone).strip(): return None`(+빈 sigungu·area_cd 동일). + 코사인 거리 임계 초과 HIT 기각(무관 별표 승리 방지). QA: zone=None→MISS(citation 안 만듦).
2. **KINDS 4개 거짓**: 인덱서 `KINDS=['도시계획']`만(title-regex '건축할 수 있는/없는'는 도시계획 용도지역 별표 전용). README/honestScope도 "도시계획 용도지역 별표만 인덱싱"으로 정직표기. 4종 커버 주장 금지.
3. **index/fallback 의미 불일치**: `lookup_ordin` SELECT에 `AND ordin_kind='도시계획'` → HIT과 live-fallback이 같은 별표류 해소.
4. **proto_bridge sys.path**: `ganeomteo/` 디렉터리도 `sys.path.insert` + `infra/__init__.py` + 시작 시 `import infra.ordin_rag` 성공여부 로그(죽은 RAG 가시화). 안 그러면 surgical edit의 `from infra.ordin_rag import lookup_ordin`가 항상 except→live로 빠져 **RAG 조용히 죽음**.
5. **uvicorn 실행 일관성**: `uv run uvicorn app:app --app-dir ganeomteo\backend`(flat) — 내부 `from proto_bridge import GRAPH` 동작. README/runSteps 일치.
6. **area_cd5 키링**: `ordin_byeolpyo_fetch`가 `lookup_ordin(area_cd, sigungu, zone)` 호출(area_cd=pnu[:5] 이미 State에 있음). SELECT `WHERE area_cd5=%s` 1차(구-토큰 교차매칭 방지) + `sigungu_org LIKE` 보조. 인덱서도 area_cd5 저장. QA: 구-토큰 주소가 타 지자체 청크 HIT 안 함.

**MED**
7. **found 추측 누락**: sse.py `found`를 문자열추측 말고 **구조신호**로 — 해당 ToolMessage의 Command가 citation 추가 0 / JoryeVerdict='확인필요' / 실패토큰 확장셋('못찾음','없음','빈값','조회 실패','추출 실패','미확정'). 기권 라이브 노출 보장.
8. **cp949 콘솔 크래시**: build_index·run_qa 상단 `sys.stdout.reconfigure(encoding='utf-8', errors='replace')`(stderr도). PYTHONIOENCODING은 백업. 빌드 끝 `SELECT count(*) GROUP BY area_cd5` 출력(빈/부분 인덱스 가시화).
9. **위험·금지 = 성공(영문)카드 경로**: `_derive_verdict` H1 위험·금지는 compose(영문키, terminal=completed)로 옴, abstain 아님. 픽스처에 **completed-위험·금지(영문)** + **abstain-확인필요(한글)** 둘 다. card.js가 영문/completed 형태서 '위험·금지' 헤드라인 렌더 검증.
10. **RAG-HIT 픽스처 날조금지**: 인덱스 **먼저 빌드** → 실제 `graph.invoke`(또는 직접 lookup) HIT 캡처. 양평 빌드 MISS면 정직히 rag-miss가 픽스처, README에 "RAG-HIT 미입증" 명기. 토큰수는 usage.total_tokens 실측 후 주장.
11. **thread_id 충돌**: 서버가 `/diagnose/stream`서 thread_id 생성→첫 SSE 프레임에 반환→클라가 /result·/resume에 echo. MemorySaver=단일사용자 데모 가정 명기.
12. **Documents 키불일치**: compose가 `{stage,count,status}`만 내고 items[](has_proviso) 드롭. → compose에 `has_proviso` 불린 추가하거나 card.js의 '단서(다만) 배지'·per-호 주장 제거. fixture로 documents 항목 키 assert.
13. **openai 직접의존**: `uv add openai`(transitive만이라 취약). pyproject_add에 포함.
14. **embedding 비대칭 정직**: 데모규모(zone당 별표1개) 검색은 메타필터 지배·벡터 near-decorative. README에 정직 명기(semantic RAG 품질 과장 금지).

**LOW**(가능시): connect host=127.0.0.1(타임아웃 6s→3s) / stub 결정성은 "외부API 안정 가정"으로 약화(픽스처=golden) / guard-bounce 중복누적 dedup 또는 call-count 명기 / reg_effects 2·7 매직넘버 금지(구조 invariant만) / pgvector 이미지 버전 핀 / Pretendard CDN 빼고 self-host만 / _STEP_HARDCAP=24가 실천장(80 아님) QA케이스.

## 빌드 순서 (각 단계 verify)
0. Pre-flight: docker daemon live·5433 free·.env GMS_KEY·openai/olefile/langgraph present (워크플로우 실측됨, 재확인).
1. infra/{docker-compose,schema} → `docker compose up -d` → healthy → `\dt`·EXTENSION vector 확인.
2. `uv add fastapi 'uvicorn[standard]' 'psycopg[binary]' pgvector openai` + .env PG_DSN.
3. infra/{embed,db} → smoke: `embed_one('자연녹지지역 건축')` len==3072 + db round-trip.
4. build_ordinance_index(도시계획만) → `uv run` → OK/SKIP/MISS 로그 + `count GROUP BY area_cd5` → **실제 인덱싱된 지자체에서만** 데모 케이스 선정(정직).
5. ordin_rag + surgical tools.py/state.py → regression: stub + real-LLM trace.py 양평 → agent/graph/stub 불변 + doc_index_hit 등장.
6. backend/* → `curl /diagnose/stream` data프레임→done + `/diagnose/result` 4키.
7. qa/run_qa → 멀티케이스+엣지 실제캡처 → fixtures/*.json.
8. frontend/* + Pretendard woff2 → fixture mock모드 먼저(모든 픽스처 콘솔에러0) → 라이브 SSE.
9. E2E: uvicorn → 브라우저 8000 → 양평 case 라이브트레이스+카드 → 없는주소 재입력카드.
10. QA 스윕: 전 qaMatrix 케이스(unknown-kind/unknown-verdict/missing-key/abstain/RAG-MISS/interrupt) 콘솔에러0.

## QA 매트릭스 (요지 — 단일케이스 금지)
양평 카페(real, 가능(조건부) 풀카드) / pure 가능(의제0) / 확인필요(act 빈값 강등) / **위험·금지(개발제한 seed, 영문카드)** / abstain site_geocode_failed(한글카드) / **unknown verdict 주입** / RAG HIT(인덱스 후 실캡처) / RAG MISS·DB-down(graceful fallback) / uijae 0·1·N / documents 확인필요(초지전용 DOC_SOURCE未등록) / reg_effects partial(구조invariant만, 2·7 금지) / citations 0·vworld-only·1·N / 병렬 tool_calls dedup / HITL interrupt / long-fetch stall / **_STEP_HARDCAP=24 hit→부분카드** / 결정성(픽스처 golden).

## 정직범위 (거짓완료 금지)
- **데모**: react_proto e2e 작동(stub 랜덤시드 + real gpt-5.2 양평). FastAPI 래핑은 검증된 updates 경로. GMS 3072 임베딩 실측. RAG 인덱스는 **신규 빌드**(프로토엔 pgvector 없음). 프론트 신규.
- **미구현/비데모(명시)**: **전국 아님** — 인덱싱된 도시계획 별표 지자체만 HIT, 그 외 live-fallback/확인필요. hwpx('PK') SKIP→커버리지 감소(정직). 3072>2000 ANN 없음(데모규모 OK, 전국 비확장). 부담금=금액없음(계약). roadmap/pitfalls 합성. stub record_ordinance_ruling='확인필요' 고정(멀티홉 지능은 real-LLM만). 임베딩 비대칭→메타필터 지배.
- 픽스처 전부 실제 graph.invoke 캡처(날조0). 기존 `law_fetch.py:6 OC` 평문 시크릿은 **기존**(본 작업 무관, 소유자에 플래그). GMS_KEY는 코드/로그/SSE/문서 어디에도 없음(.env, gitignore).
