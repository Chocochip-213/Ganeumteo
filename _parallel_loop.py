# -*- coding: utf-8 -*-
"""병렬 무한 페르소나 루프 — N 워커 동시(프록시 동시성 실측 OK). 각 워커: 생성기LLM→가늠터 실진단→페르소나LLM HITL→로그, 무한.
공유 GRAPH(노드 stateless·distinct thread_id로 격리), 로그는 락. 명시 kill까지. 로그=_loop_log.jsonl."""
import os, sys, json, time, re, threading, itertools, traceback
os.environ.pop("FORCE_STUB", None); os.environ.pop("APP_MODE", None)
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
sys.path[:0] = ["agent", "lawlib", "backend"]
from proto_bridge import GRAPH
from state_init import fresh_state, make_config
from langgraph.types import Command
from langchain_openai import ChatOpenAI

WORKERS = int(os.environ.get("LOOP_WORKERS", "10"))
_mk = lambda: ChatOpenAI(model=os.environ.get("LLM_MODEL", "gpt-5.5"), base_url=os.environ.get("LLM_BASE_URL"),
                         api_key=os.environ.get("LLM_API_KEY") or "x", timeout=90, max_retries=2)
LOG = "_loop_log.jsonl"
loglock = threading.Lock()
counter = itertools.count(1)

ADDR_POOL = [
    "경기도 오산시 원동 800", "경기도 수원시 팔달구 인계동 1117", "경기도 평택시 통복동 150",
    "경기도 김포시 사우동 350", "경기도 화성시 향남읍 상신리 600", "경기도 안산시 단원구 고잔동 515",
    "경기도 광주시 경안동 200", "경기도 이천시 중리동 100", "경기도 여주시 가남읍 태평리 350",
    "경기도 평택시 청북읍 고잔리 500", "경기도 안성시 미양면 신계리 180", "경기도 성남시 분당구 정자동 178",
    "경기도 부천시 원미구 중동 1100", "경기도 평택시 비전동 1000", "경기도 안성시 공도읍 만정리 750",
]
USE_CATS = [
    "단독주택 신축", "다세대/다가구주택 신축", "일반음식점/카페 신축", "제2종근생→위락(단란주점) 용도변경",
    "근생 소매점 신축", "헬스장/체육시설 용도변경", "의원/병원 신축", "동물병원 용도변경",
    "숙박/생활숙박시설 신축", "교회/사찰 종교시설 신축", "노유자(요양원/어린이집) 신축", "물류창고 신축",
    "공장(제조) 신축", "주유소/위험물시설 신축", "태양광/발전 공작물", "장례식장/봉안당 신축",
    "오피스텔/업무시설 신축", "학원/교육연구 용도변경", "대수선 공사", "증축 공사", "철거후 신축",
]
GEN_PROMPT = (
    "건축 인허가 사전진단 테스트 시나리오 생성기다. 지정 부지·용도카테고리로 현실적 건축주 케이스를 invent해 JSON만 출력(코드펜스 없이): "
    '{"use":"구체 용도/업종","area":연면적숫자,"floors":층수숫자,"brief":"공사종류·소유/임차·규모·특수사정 1~2문장"}. '
    "**부지: %s**\n**용도카테고리: %s**\n면적·층수·소유형태·특수사정 현실적이고 다양하게. 시드=%d.")

def parse(txt):
    i = txt.index("{")
    d, _ = json.JSONDecoder().raw_decode(txt[i:])   # 첫 JSON만 파싱(뒤 extra text 무시 — 생성기 trailing 설명 대응)
    return str(d["use"]), float(d.get("area") or 0) or None, int(d.get("floors") or 0) or None, str(d.get("brief", ""))

# 의미 검수(LLM-as-judge) — 구조 플래그(CRASH/EMPTY/BARE)가 못 잡는 법리 정오를 독립 적대검토. 정직한 확인필요(도면/사용자/심의)는 OK, 확정 법적오류만 SUSPECT.
os.makedirs("_cards", exist_ok=True)
JUDGE_PROMPT = (
    "너는 대한민국 건축 인허가 전문가(독립 적대 검수자)다. 아래 사전진단 카드를 독립적으로 법적 재검토해 *의미적 오류*만 잡아라(구조·빈칸 아님, 법리·판정의 정오).\n"
    "다음만 SUSPECT(그 외 전부 OK):\n"
    "1) false_ga(거짓가능): *확정된 사실*에서 실재하는 확정 법적 차단(용도지역 닫힌열거 제외·명문 금지·법정수치 산술초과)이 나오는데 종합 verdict가 위험·금지가 아님. "
    "**단 ①차단의 전제(대지면적·지번·권원·저촉범위 등)가 미확정이면 false_ga 아님 — verdict가 그 때문에 확인필요인 것은 정상(미확인≠금지) ②'용도 금지' 주장은 카드가 읽은 조례/별표 원문에 그 용도가 명시 금지로 열거됨을 네가 짚을 수 있을 때만 — 카드가 별표를 fetch해 '금지목록에 없음'으로 판정한 걸 네 일반지식만으로 뒤집지 마라.**\n"
    "2) false_geumji(거짓금지): 종합 verdict가 위험·금지인데 근거가 *데이터부재·범위미확인·부분저촉*뿐이고 확정 법적 근거가 없음(미확인≠금지 위반).\n"
    "3) missing(누락): 이 용도·공사에 *반드시* 필요한 핵심 의제·인허가가 카드에 통째로 없음(농지전용·산지전용·주택사업계획승인·식품위생 영업허가 등 명백한 것).\n"
    "4) wrong_law(오인용): 인용 법령·별표가 그 용도에 명백히 부적용.\n"
    "**known-정상(반복 오발 금지)**: ①단독·공동주택 부설주차=계단식 산식(1+(연면적-150)/100, 비고6 0.5미만 버림)이라 작은 연면적은 1대가 정상(균등식 200㎡/대로 2대 우기지 마라) ②동물병원·동물미용 연면적 300㎡ 미만=제1종근생 별표1 카목(제2종 오판 아님) ③운영·영업 인허가 누락은 종합 verdict가 위험·금지(건축 자체 불가)면 moot=OK(불가 프로젝트에 영업관문 불요) ④대지면적·지번 미확정發 규모 확인필요는 정상(불가로 우기지 마라).\n"
    "**환각 금지**: 도면·사용자·관할심의 의존의 *정직한 확인필요*(저촉범위·§84걸침·지구단위 도서·권원·교육환경 심의·대장정합)는 정상=OK. 막연한 의심·강화차원(주차·작성주체 정밀화)·네가 확신 못 하는 것=전부 OK. SUSPECT는 반드시 구체 법령/별표/수치를 ground에 명시. 확신 없으면 OK.\n"
    'JSON만 출력(코드펜스 없이): {"flag":"OK|SUSPECT","type":"false_ga|false_geumji|missing|wrong_law|none","conf":0~1,"issue":"한줄","ground":"구체법령(SUSPECT시 필수)"}\n\n=== 진단 카드 ===\n%s')

def pjudge(txt):
    i = txt.index("{"); d, _ = json.JSONDecoder().raw_decode(txt[i:])
    return d

def card_brief(addr, use, area, floors, card, cites):
    out = [f"[부지]{addr} [용도]{use} [연면적]{area}㎡ [층]{floors} [종합verdict]{card.get('verdict')}"]
    for L in card.get("verdict_labels", []):
        out.append(f"· {L.get('dimension')}: {L.get('status')}({L.get('blocking_level')}/{L.get('unresolved_by')}) {str(L.get('reason') or '')[:140]}")
    if cites:
        out.append("[인용] " + " | ".join(str(c)[:70] for c in cites[:8]))
    return "\n".join(out)

def find_intr(cfg):
    for t in (GRAPH.get_state(cfg).tasks or []):
        for itt in (getattr(t, "interrupts", None) or []):
            return getattr(itt, "value", itt)
    return None

def one(it, gen, persona, judge):
    rec = {"iter": it}
    try:
        addr = ADDR_POOL[(it - 1) % len(ADDR_POOL)]; use_cat = USE_CATS[(it - 1) % len(USE_CATS)]
        use, area, floors, brief = parse(gen.invoke(GEN_PROMPT % (addr, use_cat, it)).content)
        rec.update(addr=addr, use=use, area=area, floors=floors)
        _, cfg = make_config(f"par{it}_{int(time.time()*1000) % 1000000}")
        GRAPH.invoke(fresh_state(addr, use, area, floors), cfg)
        rounds = 0
        while rounds < 4:
            intr = find_intr(cfg)
            if intr is None: break
            rounds += 1
            q = intr.get("question") if isinstance(intr, dict) else str(intr)
            ans = persona.invoke(f"너는 이 부지에 '{use}'를 하려는 건축주(일반인)다. 배경:\n{brief}\n전문가 질문에 일관되게 1~3문장 한국어로만 답(꾸며내지 말고 모르면 '잘 모르겠다'):\n{q}").content
            GRAPH.invoke(Command(resume={"type": "response", "answer": ans}), cfg)
        v = GRAPH.get_state(cfg).values
        term = (v.get("_return") or {}).get("terminal_reason")
        card = (v.get("_return") or {}).get("card") or {}
        labels = card.get("verdict_labels", [])
        bare = [x.get("dimension") for x in labels if x.get("status") == "확인필요" and x.get("unresolved_by", "none") == "none"]
        cites = v.get("citations") or []
        jr = {}
        if term == "completed" and labels:   # 완료·비어있지않은 카드만 의미검수(크래시/빈카드는 구조플래그가 이미 잡음)
            try: jr = pjudge(judge.invoke(JUDGE_PROMPT % card_brief(addr, use, area, floors, card, cites)).content)
            except Exception as je: jr = {"flag": "JUDGE_ERR", "issue": f"{type(je).__name__}:{str(je)[:60]}"}
        flag = ("CRASH" if term in ("llm_error", "context_overflow", "error") else "GEOFAIL" if term == "site_geocode_failed"
                else "EMPTY" if (term == "completed" and not labels) else "BARE" if bare
                else "SUSPECT" if jr.get("flag") == "SUSPECT" else "")
        rec.update(verdict=card.get("verdict"), terminal=term, hitl=rounds, axes=len(labels), bare=bare, judge=jr, flag=flag)
        if flag in ("SUSPECT", "BARE", "EMPTY", "CRASH"):   # 조사대상만 full card dump(in-memory checkpointer 격리라 외부서 못 꺼냄)
            try: json.dump({"case": {"addr": addr, "use": use, "area": area, "floors": floors, "brief": brief}, "verdict": card.get("verdict"), "card": card, "cites": [str(c)[:200] for c in cites], "judge": jr}, open(f"_cards/par{it}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            except Exception: pass
    except Exception as e:
        rec.update(flag="EXC", err=f"{type(e).__name__}: {str(e)[:160]}")
        if any(k in str(e) for k in ("usage limit", "Too Many Requests", "rate limit", "429")):
            time.sleep(600)   # 프록시 쿼터 소진 — EXC 스핀(프록시 hammering) 대신 백오프, 쿼터 리셋 자동 대기
    with loglock:
        open(LOG, "a", encoding="utf-8").write(json.dumps(rec, ensure_ascii=False) + "\n")
    j = rec.get("judge") or {}
    print(f"[{it}] {str(rec.get('use'))[:24]} @ {str(rec.get('addr'))[-9:]} -> {rec.get('verdict')} ax{rec.get('axes')} {rec.get('flag') or 'OK'}" + (f" !{j.get('type')}:{str(j.get('issue'))[:48]}" if rec.get('flag') == 'SUSPECT' else ""), flush=True)

def worker():
    gen, persona, judge = _mk(), _mk(), _mk()   # per-worker LLM(공유 client 동시성 회피) — 생성·페르소나·의미검수 분리
    while True:
        try: one(next(counter), gen, persona, judge)
        except Exception: traceback.print_exc(); time.sleep(2)

print(f"=== 병렬 페르소나 루프 시작: {WORKERS} 워커 ===", flush=True)
ts = [threading.Thread(target=worker, daemon=True) for _ in range(WORKERS)]
for t in ts: t.start()
for t in ts: t.join()
