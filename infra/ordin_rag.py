# -*- coding: utf-8 -*-
"""런타임 조례 RAG 조회. HIT→dict / MISS·DB-down·예외→None(절대 raise 안 함 → live fallback).
검수: zone-None 임베딩오염 가드(#1) · zone 정확매칭+임베딩 tiebreak(메타지배 정직 #14) · ordin_kind/chunk_type 필터(#3) · 거리임계 · numpy 쿼리벡터."""
import numpy as np
from infra.embed import embed_one
from infra import db

_DIST_MAX = 0.85          # 코사인거리 임계 — 초과 시 무관 별표로 보고 MISS(degenerate 방지 #1)
_SQL = """
SELECT chunk_id, ordin_name, byeolpyo_no, byeolpyo_title, body, extract_method, eff_date,
       embedding <=> %s AS dist
FROM ordin_chunk
WHERE {scope} AND ordin_kind='도시계획' AND chunk_type='별표' {zonef}
ORDER BY embedding <=> %s
LIMIT 1
"""


def lookup_ordin(sigungu, zone, area_cd=""):
    # 결측 가드(#1): zone 없으면 'None 안에서…' 임베딩 → 거짓 HIT → 차단
    if not zone or not str(zone).strip():
        return None
    sig = str(sigungu).strip() if sigungu else ""
    acd = str(area_cd).strip() if area_cd else ""
    if not sig and not acd:
        return None
    z = str(zone).strip()
    try:
        qv = embed_one(f"{z} 안에서 건축할 수 있는 건축물")
        if qv is None:
            return None
        qv = np.asarray(qv, dtype="float32")
        # 정확 키(area_cd5) 우선, 없으면 sigungu_org LIKE(데모 지자체는 명칭 명확)
        if acd:
            scope, sp = "area_cd5=%s", [acd]
        else:
            scope, sp = "sigungu_org LIKE %s", [f"%{sig}%"]
        with db.connect(timeout=3) as c:
            row = None
            # 1차: zone 정확매칭(메타 지배 — 올바른 별표 결정적 선택)
            for zf, zp in ((" AND zone LIKE %s", [f"%{z}%"]), ("", [])):
                q = _SQL.format(scope=scope, zonef=zf)
                row = c.execute(q, [qv, *sp, *zp, qv]).fetchone()
                if row:
                    break
        if not row:
            return None
        dist = float(row[7])
        if dist > _DIST_MAX:
            return None
        return {"chunk_id": row[0], "ordin_name": row[1], "byeolpyo_no": row[2], "byeolpyo_title": row[3],
                "body": row[4], "extract_method": row[5], "eff_date": row[6], "dist": dist}
    except Exception:
        return None
