# -*- coding: utf-8 -*-
"""GMS text-embedding-3-large 클라이언트 (3072차원). 키는 .env에서만, 절대 로깅 안 함."""
import os, time
from pathlib import Path
from openai import OpenAI

_ENV = Path(__file__).resolve().parents[1] / ".env"   # ganeomteo/.env(통합)
BASE_URL = "https://gms.ssafy.io/gmsapi/api.openai.com/v1"
EMBED_MODEL = "text-embedding-3-large"
EMBED_DIM = 3072                       # SSOT — index와 query 임베딩 동일 모델·차원 필수
TOKEN_BUDGET = 16000                   # GMS 프록시는 요청바디가 크면(실측 ~32k토큰↑) '모델 못찾음' 400 — 요청당 토큰예산 상한(실측 24k OK·32k FAIL, 마진 적용)

MAX_INPUT_TOK = 8000                   # text-embedding-3-large 입력 하드리밋 8191 — 단일입력 초과시 400. 안전 절단.

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
    def _ntok(s): return len(_ENC.encode(s))
    def _truncate(s):
        ids = _ENC.encode(s)
        return _ENC.decode(ids[:MAX_INPUT_TOK]) if len(ids) > MAX_INPUT_TOK else s
except Exception:                      # tiktoken 부재 시 문자수 근사(한국 법령 ~0.6 tok/char)
    def _ntok(s): return int(len(s) * 0.7) + 1
    def _truncate(s): return s[:MAX_INPUT_TOK * 2]   # 보수적 문자절단(2 char/tok)


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


def _budget_batches(texts, batch_size):
    # 토큰예산·개수 둘 다 상한으로 그리디 패킹(GMS 대용량요청 400 회피). 단일입력 초과시 단독 배치.
    batch, ntok = [], 0
    for t in texts:
        tt = _ntok(t)
        if batch and (ntok + tt > TOKEN_BUDGET or len(batch) >= batch_size):
            yield batch
            batch, ntok = [], 0
        batch.append(t); ntok += tt
    if batch:
        yield batch


def embed_batch(texts, batch_size=64):
    clean = [_truncate(t if (t and t.strip()) else " ") for t in texts]   # 빈입력 거부+단일입력 8k토큰 절단
    out = []
    for b in _budget_batches(clean, batch_size):
        vecs = _emb(b)
        for v in vecs:
            assert len(v) == EMBED_DIM, f"embedding dim {len(v)} != {EMBED_DIM}"
        out.extend(vecs)
    return out


def embed_one(text):
    if not text or not str(text).strip():
        return None
    return embed_batch([str(text)])[0]
