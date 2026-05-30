# -*- coding: utf-8 -*-
"""pgvector 연결 + idempotent upsert. 127.0.0.1(단일주소→정확 timeout, 검수 LOW)."""
import os
import psycopg
from pgvector.psycopg import register_vector

DEFAULT_DSN = "postgresql://gameauteo:gameauteo@127.0.0.1:5433/gameauteo"


def dsn():
    return os.environ.get("PG_DSN") or DEFAULT_DSN


def connect(timeout=3):
    conn = psycopg.connect(dsn(), connect_timeout=timeout)
    register_vector(conn)
    return conn


_UPSERT = """
INSERT INTO ordin_chunk
  (chunk_id, area_cd5, sigungu_org, ordin_name, ordin_mst, ordin_kind, chunk_type,
   byeolpyo_no, byeolpyo_title, zone, eff_date, extract_method, src_len, body, embedding, body_tsv)
VALUES
  (%(chunk_id)s, %(area_cd5)s, %(sigungu_org)s, %(ordin_name)s, %(ordin_mst)s, %(ordin_kind)s, %(chunk_type)s,
   %(byeolpyo_no)s, %(byeolpyo_title)s, %(zone)s, %(eff_date)s, %(extract_method)s, %(src_len)s, %(body)s,
   %(embedding)s, to_tsvector('simple', %(body)s))
ON CONFLICT (chunk_id) DO UPDATE SET
   body=EXCLUDED.body, embedding=EXCLUDED.embedding, body_tsv=EXCLUDED.body_tsv,
   extract_method=EXCLUDED.extract_method, src_len=EXCLUDED.src_len, eff_date=EXCLUDED.eff_date,
   indexed_at=now();
"""


def upsert_chunks(rows):
    """rows = list[dict] (위 컬럼 키). embedding은 list[float](3072). 멱등(eff_date 델타)."""
    if not rows:
        return 0
    with connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(_UPSERT, rows)
        conn.commit()
    return len(rows)
