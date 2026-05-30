# -*- coding: utf-8 -*-
"""GMS text-embedding-3-large 클라이언트 (3072차원). 키는 .env에서만, 절대 로깅 안 함."""
import os, time
from pathlib import Path
from openai import OpenAI

_ENV = Path(__file__).resolve().parents[2] / "react_proto" / ".env"   # probe/react_proto/.env
BASE_URL = "https://gms.ssafy.io/gmsapi/api.openai.com/v1"
EMBED_MODEL = "text-embedding-3-large"
EMBED_DIM = 3072                       # SSOT — index와 query 임베딩 동일 모델·차원 필수


def _load_key():
    if os.environ.get("GMS_KEY"):
        return os.environ["GMS_KEY"]
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("GMS_KEY="):
            return s.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("GMS_KEY not found in env or .env")


_client = OpenAI(api_key=_load_key(), base_url=BASE_URL)


def _emb(texts):
    last = None
    for attempt in range(5):                 # GMS 프록시 early-close 대비 재시도
        try:
            r = _client.embeddings.create(model=EMBED_MODEL, input=texts)
            data = sorted(r.data, key=lambda d: d.index)   # 배치 순서 보존
            return [list(d.embedding) for d in data]
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"embedding failed after 5 tries: {type(last).__name__}")


def embed_batch(texts, batch_size=64):
    clean = [(t if (t and t.strip()) else " ") for t in texts]   # GMS는 빈 입력 거부
    out = []
    for i in range(0, len(clean), batch_size):
        vecs = _emb(clean[i:i + batch_size])
        for v in vecs:
            assert len(v) == EMBED_DIM, f"embedding dim {len(v)} != {EMBED_DIM}"
        out.extend(vecs)
    return out


def embed_one(text):
    if not text or not str(text).strip():
        return None
    return embed_batch([str(text)])[0]
