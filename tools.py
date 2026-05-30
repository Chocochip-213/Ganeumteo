# -*- coding: utf-8 -*-
"""ReAct 도구 — 검증된 research/wf_*.py를 @tool로 래핑. 부록 G2.1: Command(update) 반환.
사실=tool fetch(원문), 인용 동반, 못 얻으면 확인필요. 내부 로직 전부 실증(wf_*.py)."""
import sys, re, io, zlib, json, urllib.request, urllib.parse, time, uuid
from typing import Annotated, Optional, List
from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.types import Command
import olefile

sys.path.insert(0, r"C:\Users\kmw16\Desktop\agent\probe\research")
import law_fetch as L            # search/service/ordin_search/ordin_service (실증)
import wf_e2e_live as W          # geo/parcel/ned/act/dig (실증 VWorld+행위제한)
import wf_docs_agent as DOC      # docs_for (시행규칙 조문 호 전수)
import wf_reg_agent as REG       # resolve (규제명→법령조회)
import wf_roadmap as RM          # author_rule (건축법§23①)
from state import Citation, UijaeItem, DocItem, StageDocs, JoryeVerdict, RegEffect, AuthorRule, ScaleLimit

_JIMOK = {"임": "임야", "과": "과수원", "목": "목장용지", "잡": "잡종지"}
def _S(v):
    if v is None: return ""
    if isinstance(v, list): return " ".join(_S(x) for x in v)
    return str(v)
def _tm(text, cid): return ToolMessage(text, tool_call_id=cid)


# ── 입지 ─────────────────────────────────────────────────────
@tool
def geocode(address: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """주소→좌표(x경도,y위도). VWorld req/address."""
    xy = W.geo(address, "road") or W.geo(address, "parcel")
    if not xy:
        return Command(update={"abstentions": [{"node": "geocode", "사유": "지오코딩 실패"}],
                               "terminal_reason": "site_geocode_failed",
                               "_toolcalls": ["geocode"], "messages": [_tm("지오코딩 실패", tool_call_id)]})
    return Command(update={"_xy": [xy[0], xy[1]], "_toolcalls": ["geocode"],
                           "messages": [_tm(f"좌표 x={xy[0]:.5f} y={xy[1]:.5f}", tool_call_id)]})


@tool
def get_parcel(x: float, y: float, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """좌표→필지: PNU·지목·도로접면(roadSideCodeNm)·시군구. VWorld req/data."""
    pc = W.parcel(x, y)
    pnu = pc.get("pnu")
    if not pnu:
        return Command(update={"abstentions": [{"node": "get_parcel", "사유": "필지 없음"}],
                               "_toolcalls": ["get_parcel"], "messages": [_tm("필지 조회 실패", tool_call_id)]})
    jb = pc.get("jibun", "") or ""
    jimok = (re.findall(r"[가-힣]+", jb) or [""])[-1]
    jimok = _JIMOK.get(jimok, jimok)
    addr = pc.get("addr", "") or ""
    toks = addr.split()
    sigungu = ([t for t in toks if t.endswith("시")] or [t for t in toks if t.endswith("군")]
               or [t for t in toks if t.endswith("구")] or [""])[0]
    road = W.dig(pc, "roadSideCodeNm")
    road = road[0] if road else None
    cite = Citation(source="vworld", title="필지 LP_PA_CBND_BUBUN",
                    quote=f"지목 {jimok}, 도로접면 {road}").model_dump()
    return Command(update={"pnu": pnu, "area_cd": pnu[:5], "jimok": jimok, "sigungu": sigungu,
                           "road_side": road, "citations": [cite], "_toolcalls": ["get_parcel"],
                           "messages": [_tm(f"PNU={pnu} 지목={jimok} 도로접면={road} 시군구={sigungu} ({addr})", tool_call_id)]})


@tool
def get_land_use(pnu: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """PNU→용도지역·규제중첩·UQ코드. VWorld ned getLandCharacteristics/getLandUseAttr."""
    lc = W.ned("getLandCharacteristics", pnu)
    zone = (W.dig(lc, "prposArea1Nm") or [None])[0]
    lu = W.ned("getLandUseAttr", pnu)
    uq = re.findall(r'"prposAreaDstrcCode"\s*:\s*"(UQ[A-Z][0-9]+)"', json.dumps(lu, ensure_ascii=False))
    regs = list(dict.fromkeys(W.dig(lu, "prposAreaDstrcCodeNm")))
    road = (W.dig(lc, "roadSideCodeNm") or [None])[0]   # #10 도로접면(맹지)은 토지특성에 있음
    return Command(update={"zone": zone, "zone_ucodes": uq, "reg_overlaps": regs, "road_side": road,
                           "_toolcalls": ["get_land_use"],
                           "messages": [_tm(f"용도지역={zone} 도로접면={road} UQ={uq[:3]} 규제={regs}", tool_call_id)]})


@tool
def get_land_price(pnu: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """PNU→공시지가(원/㎡). VWorld ned getIndvdLandPriceAttr."""
    raw_p = W.dig(W.ned("getIndvdLandPriceAttr", pnu, {"stdrYear": "2024"}), "pblntfPclnd")
    p = int(raw_p[0]) if raw_p and str(raw_p[0]).isdigit() else None
    upd = {"_toolcalls": ["get_land_price"], "messages": [_tm(f"공시지가={p}원/㎡", tool_call_id)]}
    if p is not None:
        upd["land_price"] = p
    else:
        upd["abstentions"] = [{"node": "get_land_price", "사유": "공시지가 미확보"}]
    return Command(update=upd)


@tool
def act_landuse(zone_ucode: str, use_type: str, area_cd: str,
                tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """행위제한 1차판정 + 조례위임 감지. data.go.kr 1613000.
    입력: zone_ucode=get_land_use의 UQ코드 말단, use_type=용도, area_cd=get_parcel의 area_cd(PNU 앞5).
    반환 act_verdict∈{가능(법령직접), 조례확인필요(혼재), 조례확인필요}. 빈값·혼재=조례위임(_delegated=True) → 단정 말고 ordin_byeolpyo_fetch로 진행."""
    nm = "일반음식점" if "음식" in use_type or "카페" in use_type else use_type
    rg = W.act(zone_ucode, nm, area_cd)
    has_y, has_n = (rg and "가능" in rg), (rg and "금지" in rg)
    if has_y and not has_n:
        v, dele = "가능(법령직접)", False
    elif has_y and has_n:
        v, dele = "조례확인필요(혼재)", True   # 가능·금지 혼재 → 단정 금지(#4)
    elif has_n:
        v, dele = "조례확인필요", True         # 금지=입지제한/조례위임 가능성
    else:
        v, dele = "조례확인필요", True         # 빈값=조례 위임
    return Command(update={"act_verdict": v, "act_reg_raw": rg, "_delegated": dele,
                           "_toolcalls": ["act_landuse"],
                           "messages": [_tm(f"행위제한 {nm}@{zone_ucode}: REG_NM={rg or '빈값'} → {v}", tool_call_id)]})


# ── 조례 별표 BodyText (멀티홉 1번째 홉) ─────────────────────
def _ordin_bodytext(sigungu, zone):
    s = L.ordin_search(f"{sigungu} 도시계획")
    items = s.get("items") or []
    cand = [it for it in items if "계획" in _S(it.get("자치법규명")) and sigungu in _S(it.get("자치법규명"))] or items
    if not cand: return None, {}
    mst = cand[0].get("자치법규일련번호") or cand[0].get("MST")
    nm = _S(cand[0].get("자치법규명"))
    j = L.ordin_service(mst)
    bu = j.get("별표", {}).get("별표단위") or []
    if isinstance(bu, dict): bu = [bu]
    tgt = None
    for b in bu:
        ti = _S(b.get("별표제목"))
        if zone in ti and ("건축할 수 있는" in ti or "건축할 수 없는" in ti):
            tgt = b; break
    if not tgt: return None, {"조례명": nm}
    url = _S(tgt.get("별표첨부파일명"))
    raw = None
    for _ in range(4):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Connection": "close"}), timeout=40).read(); break
        except Exception:
            time.sleep(1.5)
    if not raw or raw[:4] != bytes.fromhex("d0cf11e0"): return None, {"조례명": nm, "별표": _S(tgt.get("별표번호"))}
    try:
        o = olefile.OleFileIO(io.BytesIO(raw))
        try:
            full = zlib.decompress(o.openstream("BodyText/Section0").read(), -15).decode("utf-16-le", "ignore")
        except Exception:
            full = o.openstream("PrvText").read().decode("utf-16-le", "ignore")
        o.close()
    except Exception:
        return None, {"조례명": nm, "별표": _S(tgt.get("별표번호"))}
    clean = re.sub(r"\s+", " ", re.sub(r"[^가-힣0-9().,ㆍ· ]", " ", full))
    return clean, {"조례명": nm, "별표": _S(tgt.get("별표번호")) + " " + _S(tgt.get("별표제목"))[:30]}


@tool
def ordin_byeolpyo_fetch(sigungu: str, zone: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """지자체 도시계획조례 '{zone} 건축가능 별표' BodyText. 사전인덱스 HIT 우선→MISS면 라이브 추출. 멀티홉 1홉."""
    # 가늠터 RAG: 사전인덱싱 HIT-first (infra 미연결/MISS/예외면 조용히 라이브 폴백 — Command 형태 불변)
    try:
        from infra.ordin_rag import lookup_ordin
        hit = lookup_ordin(sigungu, zone)
    except Exception:
        hit = None
    if hit:
        body = hit["body"]
        art = f"{hit['byeolpyo_no']} {str(hit['byeolpyo_title'])[:30]}"
        cite = Citation(source="ordin", law_name=hit["ordin_name"], article=art,
                        quote=body[:110], extract_method="인덱스청크").model_dump()
        return Command(update={"citations": [cite], "_delegated": True, "doc_index_hit": True,
                               "_toolcalls": ["ordin_byeolpyo_fetch"],
                               "messages": [_tm(f"[조례 별표 BodyText(인덱스):{art}]\n{body[:2500]}", tool_call_id)]})
    # ── 라이브 폴백(기존 경로 — 불변) ──
    text, meta = _ordin_bodytext(sigungu, zone)
    if not text:
        return Command(update={"jorye_verdicts": [JoryeVerdict(ordin_name=meta.get("조례명"), verdict="확인필요",
                               reason="별표 추출 실패(미인덱싱/hwpx)").model_dump()],
                               "doc_index_hit": False, "_toolcalls": ["ordin_byeolpyo_fetch"],
                               "messages": [_tm(f"조례 별표 추출 실패: {meta}", tool_call_id)]})
    cite = Citation(source="ordin", law_name=meta["조례명"], article=meta["별표"], quote=text[:110],
                    extract_method="BodyText").model_dump()
    # 멀티홉 본문을 ToolMessage로 → (실 LLM) agent가 호목참조 읽고 다음 홉 결정
    return Command(update={"citations": [cite], "_delegated": True, "doc_index_hit": False, "_toolcalls": ["ordin_byeolpyo_fetch"],
                           "messages": [_tm(f"[조례 별표 BodyText:{meta['별표']}]\n{text[:2500]}", tool_call_id)]})


@tool
def law_byeolpyo_fetch(law_name: str, byeolpyo_kw: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """법령 별표 inline 텍스트(예: 건축법 시행령 별표1 용도별 건축물). 멀티홉 2홉(호목 해소)."""
    a = L.search(law_name, "law")["LawSearch"]["law"]
    if isinstance(a, dict): a = [a]
    cand = [x for x in a if x.get("법령명한글") == law_name]
    if not cand:
        return Command(update={"_toolcalls": ["law_byeolpyo_fetch"], "messages": [_tm(f"{law_name} 없음", tool_call_id)]})
    j = L.service(cand[0]["법령일련번호"], "law")
    bu = j["법령"].get("별표", {}).get("별표단위")
    bu = bu if isinstance(bu, list) else [bu]
    numkey = (re.findall(r"\d+", byeolpyo_kw) or [""])[0]   # "별표 1 용도별..."→"1"
    for b in bu:
        if not isinstance(b, dict):
            continue
        bno = _S(b.get("별표번호")).lstrip("0")
        bti = _S(b.get("별표제목"))
        if (numkey and numkey == bno) or (byeolpyo_kw.strip() and byeolpyo_kw.strip() in bti) or ("용도별" in bti and "용도" in byeolpyo_kw):
            t = re.sub(r"\s+", " ", _S(b.get("별표내용")))
            cite = Citation(source="law", law_name=law_name, article=_S(b.get("별표번호")), quote=t[:200]).model_dump()
            return Command(update={"citations": [cite], "_toolcalls": ["law_byeolpyo_fetch"],
                                   "messages": [_tm(f"[{law_name} {byeolpyo_kw}]\n{t[:7000]}", tool_call_id)]})
    return Command(update={"_toolcalls": ["law_byeolpyo_fetch"], "messages": [_tm("별표 못찾음", tool_call_id)]})


# ── 서류·규모·작성주체 ───────────────────────────────────────
@tool
def docs_for_stage(stage_key: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """단계별 시행규칙 첨부서류 호 전수(누락0). docs_for(stage).
    입력 stage_key: '건축허가'·'착공신고'·'사용승인' + record_uijae로 만든 의제 stage_key(농지전용/산지전용/개발행위/초지전용/사도개설)만. 'PNU'·'의제단계' 등 placeholder 금지."""
    r = DOC.docs_for(stage_key)
    if r["상태"] != "전수확보":
        return Command(update={"documents": [StageDocs(stage_key=stage_key, status="확인필요").model_dump()],
                               "_toolcalls": ["docs_for_stage"], "messages": [_tm(f"{stage_key} 서류 확인필요", tool_call_id)]})
    items = [DocItem(ho=d["호"], doc_name=d["서류"], has_proviso=d["단서있음"]).model_dump() for d in r["서류"]]
    sd = StageDocs(stage_key=stage_key, law=r["법령"], article=r["조"], count=r["건수"], items=items).model_dump()
    return Command(update={"documents": [sd], "_toolcalls": ["docs_for_stage"],
                           "messages": [_tm(f"{stage_key} 첨부 {r['건수']}호 전수({r['법령']} {r['조']})", tool_call_id)]})


@tool
def compute_scale(floor_area: float, floor_count: int, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """연면적/층수→규모상한 결정적 룰(에너지≥500·구조안전≥200 or 2층)."""
    sl = ScaleLimit(energy_saving_required=floor_area >= 500,
                    structural_safety_required=(floor_area >= 200 or floor_count >= 2),
                    notes=[f"연면적 {floor_area}㎡·{floor_count}층"]).model_dump()
    return Command(update={"scale_limits": sl, "_toolcalls": ["compute_scale"],
                           "messages": [_tm(f"규모상한: 에너지={sl['energy_saving_required']} 구조안전={sl['structural_safety_required']}", tool_call_id)]})


@tool
def author_rule_tool(floor_area: float, work_type: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """작성주체(건축사 필수 여부). 건축법 §23① 라이브 + 면적룰."""
    a = RM.author_rule(int(floor_area), work_type or "신축")
    au = AuthorRule(requires_architect=("건축사 필수" in a["이번_케이스"]), reason=a["사유"]).model_dump()
    cite = Citation(source="law", law_name="건축법", article="§23①", quote=a["원칙"]).model_dump()
    return Command(update={"author": au, "citations": [cite], "_toolcalls": ["author_rule_tool"],
                           "messages": [_tm(f"작성주체: {a['이번_케이스']} ({a['사유']})", tool_call_id)]})


@tool
def reg_effect_resolve_tool(reg_names: List[str], tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """규제명→근거 법령조문 라이브 조회(시드+검색). resolve(reg_names)."""
    out, eff = REG.resolve(reg_names), []
    for r in out:
        if r["상태"] == "근거확보":
            eff.append(RegEffect(reg_name=r["규제"], law_name=r["법령"], article=r["조"], effect=r["제목"]).model_dump())
    return Command(update={"reg_effects": eff, "_toolcalls": ["reg_effect_resolve_tool"],
                           "messages": [_tm(f"규제효과 {len(eff)}건 근거확보(/{len(out)})", tool_call_id)]})


# ── agent 판단 커밋 (record_*) ───────────────────────────────
@tool
def record_uijae(items: list, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """agent가 지목·입지로 판단한 의제 발동 목록 커밋. items=[{trigger,permit_name,stage_key}]."""
    ui = [UijaeItem(**{k: v for k, v in it.items() if k in ("trigger", "permit_name", "stage_key")}).model_dump() for it in items]
    return Command(update={"uijae": ui, "_toolcalls": ["record_uijae"],
                           "messages": [_tm(f"의제 {len(ui)}건 기록", tool_call_id)]})


@tool
def record_ordinance_ruling(verdict: str, hojeok_path: str, cited_count: int,
                            tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """agent 멀티홉 호목해소 결론 커밋. cited_count==0이면 확인필요 강등(환각가드)."""
    def _nv(x):   # prose→enum. 확인필요 신호 우선(#3 오정규화 방지)
        x = str(x)
        if any(k in x for k in ("확인필요", "확인 필요", "확정 불가", "확정할 수 없", "매칭 불가", "추출 실패", "알 수 없", "판단 불가")):
            return "확인필요"
        if "불가" in x or "금지" in x:
            return "불가"
        if "가능" in x:
            return "가능"
        return "확인필요"
    # 환각가드는 build_reasoning(basis)·route(citations==0→abstain)가 담당 → 여기선 verdict 정규화만
    v = _nv(verdict)
    return Command(update={"jorye_verdicts": [JoryeVerdict(verdict=v, reason=hojeok_path[:200]).model_dump()],
                           "_toolcalls": ["record_ordinance_ruling"],
                           "messages": [_tm(f"조례판정 기록: {v} ({hojeok_path})", tool_call_id)]})


@tool
def request_human_input(question: str, fields: list, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """사용자 확정 입력 요청(연면적·층수·용도). interrupt로 중단→Command(resume) 재개. 부록 G2.2."""
    from langgraph.types import interrupt
    ans = interrupt({"type": "need_input", "question": question, "fields": fields})
    if isinstance(ans, dict) and ans.get("type") == "reject":
        return Command(update={"terminal_reason": "aborted", "_toolcalls": ["request_human_input"],
                               "messages": [_tm("사용자 중단", tool_call_id)]})
    upd = {"_toolcalls": ["request_human_input"], "messages": [_tm(f"사용자 입력: {ans}", tool_call_id)]}
    for k in ("floor_area", "floor_count", "use_type"):
        if isinstance(ans, dict) and k in ans:
            upd[k] = ans[k]
    return Command(update=upd)


TOOLS = [geocode, get_parcel, get_land_use, get_land_price, act_landuse,
         ordin_byeolpyo_fetch, law_byeolpyo_fetch, docs_for_stage, compute_scale,
         author_rule_tool, reg_effect_resolve_tool, record_uijae, record_ordinance_ruling,
         request_human_input]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}
