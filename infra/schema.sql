-- 가늠터 조례 별표 청크 — text-embedding-3-large (3072차원)
-- 검수: pgvector ANN(HNSW/ivfflat)은 2000차원 상한 → 3072엔 ANN 인덱스 불가.
-- 데모 규모: 메타필터(area_cd5/sigungu_org)로 1개 지자체로 좁힌 뒤 정확 스캔(ORDER BY embedding <=> qv). ms급.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS ordin_chunk (
  chunk_id       TEXT PRIMARY KEY,
  area_cd5       TEXT,            -- PNU[:5] 지자체 5자리 코드 (정확 키 — 검수 fix #6)
  sigungu_org    TEXT,            -- law.go.kr 자치법규명/지자체 (LIKE 보조 narrowing)
  ordin_name     TEXT,
  ordin_mst      TEXT,
  ordin_kind     TEXT,            -- 데모=도시계획만 (검수 fix #2/#3)
  chunk_type     TEXT,            -- 별표 | 조문
  byeolpyo_no    TEXT,
  byeolpyo_title TEXT,
  zone           TEXT,            -- 용도지역(별표 제목 매칭된)
  eff_date       TEXT,
  extract_method TEXT,            -- BodyText | PrvText(캡)
  src_len        INT,
  body           TEXT,
  embedding      vector(3072) NOT NULL,
  body_tsv       tsvector,
  indexed_at     TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_ordin_area    ON ordin_chunk (area_cd5);
CREATE INDEX IF NOT EXISTS ix_ordin_sigungu ON ordin_chunk (sigungu_org);
CREATE INDEX IF NOT EXISTS ix_ordin_kind    ON ordin_chunk (ordin_kind, chunk_type);
CREATE INDEX IF NOT EXISTS ix_ordin_tsv     ON ordin_chunk USING GIN (body_tsv);
