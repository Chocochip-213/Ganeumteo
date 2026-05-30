# -*- coding: utf-8 -*-
"""랜덤 좌표(시드)로 ReAct 프로토타입 e2e 실행 — 과적합 체크.
사용: uv run python run.py [seed] [N]   (PYTHONIOENCODING=utf-8 권장)
LLM 키(ANTHROPIC_API_KEY) 있으면 진짜 ReAct, 없으면 stub-planner(그래프·도구·브리지는 실제 구동)."""
import sys, random
from langchain_core.messages import HumanMessage
from graph import build_graph

# 내륙 앵커(바다 회피) + 지터 → 시드 기반 랜덤 좌표(우리가 설계 안 한 임의 위치)
ANCHORS = [(127.49, 36.64), (127.15, 35.82), (128.73, 36.57), (127.92, 37.34), (128.08, 35.18),
           (127.11, 36.81), (127.73, 37.88), (126.85, 35.16), (127.93, 36.99), (128.11, 36.14)]


def fresh_state(addr, xy):
    # ★ LLM은 State 타입필드를 못 읽음 → 초기 HumanMessage로 좌표·용도·규모 전달(stub은 State 직독)
    task = HumanMessage(
        f"좌표 x={xy[0]} y={xy[1]} (주소 미상, 좌표로 시작). 용도=카페(일반음식점), 연면적=264㎡, 층수=1, 신축. "
        f"이 땅의 건축 인허가 사전진단을 수행하라. 좌표가 있으니 geocode는 생략하고 get_parcel(x={xy[0]}, y={xy[1]})부터 시작하라.")
    return {"messages": [task], "address": addr, "use_type": "카페", "floor_area": 264.0, "floor_count": 1,
            "work_type": "신축", "_xy": xy, "reg_overlaps": [], "uijae": [], "documents": [],
            "reg_effects": [], "jorye_verdicts": [], "citations": [], "abstentions": [], "_toolcalls": [], "_steps": 0}


def run_one(graph, addr, xy):
    import uuid
    cfg = {"recursion_limit": 80, "configurable": {"thread_id": "t-" + uuid.uuid4().hex[:8]}}
    return graph.invoke(fresh_state(addr, xy), cfg)


if __name__ == "__main__":
    import os
    if "stub" in sys.argv:                     # 'stub' 인자 → LLM 우회(빠른 광역 검증)
        os.environ["FORCE_STUB"] = "1"
        sys.argv = [a for a in sys.argv if a != "stub"]
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    graph, mode = build_graph()
    print(f"=== ReAct 프로토타입 e2e / agent={mode} / seed={seed} / N={n} ===")
    random.seed(seed)
    for i in range(n):
        ax, ay = random.choice(ANCHORS)
        lon = round(ax + random.uniform(-0.06, 0.06), 5)
        lat = round(ay + random.uniform(-0.06, 0.06), 5)
        addr = f"(rand {lon},{lat})"
        print(f"\n--- 샘플 {i + 1}: {addr} ---")
        try:
            out = run_one(graph, addr, [lon, lat])
            card = out.get("_card")
            if not card:
                print("  (카드 없음) terminal:", out.get("terminal_reason"), "abst:", out.get("abstentions"))
                continue
            print("  판정:", card.get("verdict"), "| terminal:", out.get("terminal_reason"))
            print("  입지: 지목=", out.get("jimok"), "용도지역=", out.get("zone"),
                  "도로접면=", out.get("road_side"), "공시지가=", out.get("land_price"))
            print("  행위제한:", out.get("act_verdict"), out.get("act_reg_raw"))
            print("  의제:", [u["permit_name"] for u in card.get("uijae", [])])
            print("  서류:", [(d["stage"], d["count"], d["status"]) for d in card.get("documents", [])])
            print("  규제효과:", [r["reg_name"] for r in (card.get("reg_effects") or [])][:5])
            print("  작성주체 건축사필수:", (card.get("author") or {}).get("requires_architect"))
            lr = card.get("legal_reasoning") or {}
            print("  논증단계:", len(lr.get("steps", [])), "| citations:", card.get("citations"),
                  "| 도구호출:", len(out.get("_toolcalls", [])))
        except Exception as e:
            import traceback
            print("  ERROR:", repr(e))
            traceback.print_exc()
