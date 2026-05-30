# -*- coding: utf-8 -*-
"""가늠터 FastAPI — react_proto 그래프를 SSE로 래핑 + 프론트 same-origin 서빙.
실행: uv run uvicorn app:app --app-dir <ganeomteo\\backend> --port 8000  (검수 fix#5: flat import)
단일사용자 데모 가정(MemorySaver in-proc). thread_id는 서버 생성→첫 SSE 프레임 반환(fix#11)."""
import os
import json
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from proto_bridge import GRAPH
from state_init import fresh_state, make_config
import sse

_FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
app = FastAPI(title="가늠터")


@app.get("/diagnose/stream")
def diagnose_stream(address: str, use_type: str, floor_area: float = None, floor_count: int = None, thread_id: str = None):
    tid, cfg = make_config(thread_id)
    st = fresh_state(address, use_type, floor_area, floor_count)

    def gen():
        meta = {"seq": 0, "ts_seq": 0, "kind": "meta", "node": None, "label": "접수",
                "detail": {"thread_id": tid, "address": address, "use_type": use_type,
                           "floor_area": floor_area, "floor_count": floor_count}}
        yield "data: " + json.dumps(meta, ensure_ascii=False) + "\n\n"
        yield from sse.run_stream(GRAPH, st, cfg)

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


@app.get("/diagnose/resume")
def diagnose_resume(thread_id: str, floor_area: float = None, floor_count: int = None,
                    use_type: str = None, reject: bool = False):
    _, cfg = make_config(thread_id)
    if reject:
        resume = {"type": "reject"}
    else:
        resume = {k: v for k, v in (("floor_area", floor_area), ("floor_count", floor_count),
                                    ("use_type", use_type)) if v is not None}
    return StreamingResponse(sse.run_stream(GRAPH, None, cfg, resume=resume),
                             media_type="text/event-stream", headers=_SSE_HEADERS)


@app.get("/diagnose/result")
def diagnose_result(thread_id: str):
    """완료 후 ReturnEnvelope(_return: 4키) + 전체 citation 객체(카드 렌더용) + 좌표(카카오맵용)."""
    _, cfg = make_config(thread_id)
    vals = GRAPH.get_state(cfg).values
    body = {"_return": vals.get("_return"), "citations": vals.get("citations", []),
            "xy": vals.get("_xy"), "pnu": vals.get("pnu"), "address": vals.get("address"),
            "jimok": vals.get("jimok"), "zone": vals.get("zone")}
    return JSONResponse(content=json.loads(json.dumps(body, ensure_ascii=False, default=str)))


@app.get("/config")
def config():
    """프론트 설정 — 카카오 JS키는 .env에서(코드 하드코딩 금지). 없으면 빈값→맵 생략."""
    return {"kakao_js_key": os.environ.get("KAKAO_KEY", "")}


# 정적 프론트(same-origin, CORS 불필요) — /diagnose/* 라우트 뒤에 마운트해 우선순위 유지
app.mount("/", StaticFiles(directory=str(_FRONTEND), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
