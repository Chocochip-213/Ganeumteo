# -*- coding: utf-8 -*-
"""ReAct 도구 — 검증된 research/wf_*.py를 @tool로 래핑. 부록 G2.1: Command(update) 반환.
사실=tool fetch(원문), 인용 동반, 못 얻으면 확인필요. 내부 로직 전부 실증(wf_*.py)."""
import sys, re, io, zlib, json, urllib.request, urllib.parse, time, uuid, datetime
from typing import Annotated, Optional, List, Literal
from pydantic import Field
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
from state import Citation, UijaeItem, DocItem, StageDocs, JoryeVerdict, RegEffect, AuthorRule, ScaleLimit, LevyItem
import math

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
    raw_area = (W.dig(lc, "lndpclAr") or [None])[0]      # 대지면적 — envelope·부담금 입력. 0=미상/실제0 구분불가 → None
    try:
        land_area = float(raw_area) if raw_area not in (None, "", "0") else None
    except (TypeError, ValueError):
        land_area = None
    upd = {"zone": zone, "zone_ucodes": uq, "reg_overlaps": regs, "road_side": road,
           "_toolcalls": ["get_land_use"],
           "messages": [_tm(f"용도지역={zone} 대지면적={land_area}㎡ 도로접면={road} UQ={uq[:3]} 규제={regs}", tool_call_id)]}
    if land_area is not None:
        upd["land_area"] = land_area
    return Command(update=upd)


@tool
def get_land_price(pnu: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """PNU→공시지가(원/㎡). VWorld ned getIndvdLandPriceAttr. 시계열 전체를 받아 기준연도 내림차순 최신값 채택(연도 하드코딩 없음)."""
    rows = W.ned("getIndvdLandPriceAttr", pnu)   # stdrYear 미지정 → 전 연도 시계열 반환
    pairs = []                                    # 레코드별 (기준연도, 공시지가) 묶음 — 최신연도 채택용
    for rec in re.findall(r"\{[^{}]*\}", json.dumps(rows, ensure_ascii=False)):
        ym = re.search(r'"stdrYear"\s*:\s*"(\d{4})"', rec)
        pm = re.search(r'"pblntfPclnd"\s*:\s*"(\d+)"', rec)
        if ym and pm and int(pm.group(1)) > 0:
            pairs.append((int(ym.group(1)), int(pm.group(1))))
    p = max(pairs)[1] if pairs else None          # 기준연도 desc 정렬 후 최신값
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
    입력: zone_ucode=get_land_use의 UQ코드 말단. use_type=**건축법 용도분류상 시설명**(사용자 표현을 건축법 용도로 해석해 전달 — 예 카페→일반음식점, 사무실→업무시설, 다세대→공동주택. API가 이 시설명으로 행위제한 조회). area_cd=get_parcel의 area_cd(PNU 앞5).
    반환 act_verdict∈{가능(법령직접), 조례확인필요(혼재), 조례확인필요}. 빈값·혼재=조례위임(_delegated=True) → 단정 말고 ordin_byeolpyo_fetch로 진행."""
    rg = W.act(zone_ucode, use_type, area_cd)   # 용도 해석은 LLM이(도구는 받은 시설명 그대로 조회 — 하드코딩 맵 제거)
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
                           "messages": [_tm(f"행위제한 {use_type}@{zone_ucode}: REG_NM={rg or '빈값'} → {v}", tool_call_id)]})


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
    """국가법령(본법/시행령/시행규칙)의 별표 inline 텍스트. 어느 법이든.
    입력: law_name=법령명. 정식명이 안 맞으면 검색 후보 목록을 돌려주니, 그 중 맞는 정식명으로 다시 호출하라(여러 이름 시도 OK). byeolpyo_kw=별표 번호('1') 또는 제목 키워드('용도별','허용행위').
    용도: 조례 별표가 가리킨 국가법령 별표 해소, 또는 행위제한이 특정 법령에 있을 때 그 법의 별표 직접 조회."""
    a = L.search(law_name, "law")["LawSearch"]["law"]
    rs = [x for x in (a if isinstance(a, list) else [a]) if isinstance(x, dict)]
    cand = [x for x in rs if x.get("법령명한글") == law_name]
    if not cand:   # 정확매칭 없음 → 후보를 LLM에 돌려줘 재시도 유도(직접 휴리스틱 매칭 안 함 — LLM이 고름)
        names = [x.get("법령명한글", "") for x in rs[:6]]
        msg = (f"EMPTY '{law_name}' 정확 매칭 없음. 검색된 법령 후보: {names}. 이 중 맞는 정식 법령명으로 다시 호출하라."
               if names else f"FAIL '{law_name}' 검색 0건 → 법령명을 바꿔 다시 시도.")
        return Command(update={"_toolcalls": ["law_byeolpyo_fetch"], "messages": [_tm(msg, tool_call_id)]})
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


def _parse_article(article):
    """'84'·'제84조'·'47의2'·'85의2' → (조문번호, 가지번호 or '')."""
    s = re.sub(r"[제조\s]", "", _S(article))
    m = re.match(r"(\d+)(?:의(\d+))?", s)
    if not m:
        return "", ""
    return m.group(1), (m.group(2) or "")


def _fmt_article(u):
    """조문단위 dict → 표제+본문+항·호·목 평문(인용용)."""
    out = []
    title = _S(u.get("조문제목"))
    body = _S(u.get("조문내용"))
    if body:
        out.append(body.strip())
    hangs = u.get("항")
    if hangs:
        hangs = hangs if isinstance(hangs, list) else [hangs]
        for h in hangs:
            if not isinstance(h, dict):
                continue
            hc = _S(h.get("항내용"))
            if hc:
                out.append(hc.strip())
            hos = h.get("호")
            if hos:
                hos = hos if isinstance(hos, list) else [hos]
                for ho in hos:
                    if not isinstance(ho, dict):
                        continue
                    hoc = _S(ho.get("호내용"))
                    if hoc:
                        out.append(hoc.strip())
                    moks = ho.get("목")
                    if moks:
                        moks = moks if isinstance(moks, list) else [moks]
                        for mk in moks:
                            mc = _S(mk.get("목내용")) if isinstance(mk, dict) else _S(mk)
                            if mc:
                                out.append(mc.strip())
    return title, re.sub(r"\s+", " ", " ".join(out))


@tool
def law_article_fetch(law_name: str, article: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """국가법령(본법/시행령/시행규칙)의 **조문**(별표 아님) inline 텍스트. law_byeolpyo_fetch의 형제.
    입력: law_name=법령명. 정식명이 안 맞으면 검색 후보 목록을 돌려주니, 그 중 맞는 정식명으로 다시 호출하라(여러 이름 시도 OK). article=조문번호('84'·'제84조'·'47의2'·'85의2').
    용도: 시행령 §84/§85(건폐율·용적률 상한)·§86(일조)·농지법 §38·시행령 §53(부담금율)·시행규칙 §47의2(부담금 단가상한)·경관법 시행령 §18/§19(경관심의 임계)·영향평가 시행령 임계 등 **값을 LLM이 원문서 읽어** 다른 도구 인자로 전달하는 공급원."""
    a = L.search(law_name, "law")["LawSearch"]["law"]
    rs = [x for x in (a if isinstance(a, list) else [a]) if isinstance(x, dict)]
    cand = [x for x in rs if x.get("법령명한글") == law_name]
    if not cand:   # 정확매칭 없음 → 후보를 LLM에 돌려줘 재시도 유도(휴리스틱 매칭 안 함 — LLM이 고름)
        names = [x.get("법령명한글", "") for x in rs[:6]]
        msg = (f"EMPTY '{law_name}' 정확 매칭 없음. 검색된 법령 후보: {names}. 이 중 맞는 정식 법령명으로 다시 호출하라."
               if names else f"FAIL '{law_name}' 검색 0건 → 법령명을 바꿔 다시 시도.")
        return Command(update={"_toolcalls": ["law_article_fetch"], "messages": [_tm(msg, tool_call_id)]})
    j = L.service(cand[0]["법령일련번호"], "law")
    units = j["법령"]["조문"]["조문단위"]
    units = units if isinstance(units, list) else [units]
    jono, branch = _parse_article(article)
    if not jono:
        return Command(update={"_toolcalls": ["law_article_fetch"],
                               "messages": [_tm(f"조문번호 해석 실패: '{article}'", tool_call_id)]})
    for u in units:
        if not isinstance(u, dict) or u.get("조문여부") != "조문":
            continue
        if str(u.get("조문번호")) != jono:
            continue
        ubr = _S(u.get("조문가지번호")).strip()
        ubr = "" if ubr in ("0", "") else ubr
        if branch != ubr:
            continue
        title, full = _fmt_article(u)
        label = f"제{jono}조" + (f"의{branch}" if branch else "")
        cite = Citation(source="law", law_name=law_name, article=f"{label}({title})" if title else label,
                        quote=full[:200]).model_dump()
        return Command(update={"citations": [cite], "_toolcalls": ["law_article_fetch"],
                               "messages": [_tm(f"[{law_name} {label}{('('+title+')') if title else ''}]\n{full[:7000]}", tool_call_id)]})
    return Command(update={"_toolcalls": ["law_article_fetch"],
                           "messages": [_tm(f"'{law_name}' 제{jono}조{('의'+branch) if branch else ''} 조문 못찾음(번호 확인 후 재시도).", tool_call_id)]})


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
def compute_envelope(land_area_m2: float, bcr_pct: float, far_pct: float,
                     tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """건폐율·용적률 → 최대 건축면적·연면적·약식층수(법 산식만, 결정적).
    산식: 최대건축면적=대지면적×건폐율%, 최대연면적=대지면적×용적률%, 약식층수=연면적/건축면적(상한 가늠).
    **bcr_pct(건폐율%)·far_pct(용적률%)는 인자 — LLM이 law_article_fetch로 국토계획법 시행령 §84/§85 또는 도시계획조례서 읽은 실제치를 전달**(도구에 용도지역→율 하드코딩 없음).
    ScaleLimit를 확장(compute_scale와 같은 scale_limits 필드, envelope 3필드 채움). 용적률 법정상한은 범위(계획관리 50~100% 등)라 조례 실제치 아니면 envelope_note에 '법정상한 기준·실제치 확인필요' 강등 권장."""
    max_bldg = round(land_area_m2 * bcr_pct / 100.0, 1)
    max_floor = round(land_area_m2 * far_pct / 100.0, 1)
    approx = round(max_floor / max_bldg, 1) if max_bldg else None
    sl = ScaleLimit(energy_saving_required=max_floor >= 500,
                    structural_safety_required=(max_floor >= 200 or (approx or 0) >= 2),
                    notes=[f"대지 {land_area_m2}㎡ 건폐율 {bcr_pct}% 용적률 {far_pct}%"],
                    max_building_area=max_bldg, max_floor_area=max_floor, approx_floors=approx,
                    envelope_note="상한·가늠치(설계 後 확정). 율은 LLM이 시행령§84/§85·조례서 읽어 전달").model_dump()
    return Command(update={"scale_limits": sl, "_toolcalls": ["compute_envelope"],
                           "messages": [_tm(f"envelope: 최대건축면적={max_bldg}㎡ 최대연면적={max_floor}㎡ 약식층수≈{approx} (건폐율{bcr_pct}%·용적률{far_pct}%)", tool_call_id)]})


@tool
def parking_quota(use_type: str, floor_area: float, base_area_m2: float,
                  tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """부설주차장 소요대수(법 산식만, 결정적). 소요대수 = ceil_05(시설면적 ÷ 용도별 기준면적). 비고6: 산정 0.5이상→올림 1대.
    **base_area_m2(용도별 기준면적, ㎡/대)는 인자 — LLM이 law_byeolpyo_fetch로 주차장법 시행령 별표1에서 해당 용도의 기준면적을 읽어 전달**(도구에 용도→기준면적 하드코딩 없음, 예시값도 안 박음 — 반드시 별표1 원문 숫자).
    조례 강화배율은 별도(미반영 시 확인필요). 면적형 기준만 — 골프 홀·수영장 정원 등 비면적형은 비대상."""
    if not base_area_m2 or base_area_m2 <= 0:
        return Command(update={"parking_req": {"status": "확인필요", "note": "기준면적(base_area_m2) 미전달 — 시행령 별표1서 용도별 기준면적 읽어 재호출"},
                               "_toolcalls": ["parking_quota"],
                               "messages": [_tm("부설주차 확인필요: 용도별 기준면적 필요(별표1)", tool_call_id)]})
    raw = floor_area / base_area_m2
    spaces = math.ceil(raw) if (raw - math.floor(raw)) >= 0.5 or raw == math.floor(raw) else math.floor(raw)
    # 비고6: 산정대수 소수 0.5이상이면 1대로 본다 → 위 ceil_05. 단 floor가 0이고 0.5미만이면 0대.
    spaces = max(spaces, 0)
    cite = Citation(source="law", law_name="주차장법 시행령", article="별표1",
                    quote=f"{use_type} 기준면적 {base_area_m2}㎡/대(LLM이 별표1서 읽어 전달)").model_dump()
    pr = {"use_type": use_type, "floor_area": floor_area, "base_area_m2": base_area_m2,
          "spaces": spaces, "status": "산출",
          "note": "부설주차 산식(ceil_05). 조례 강화배율 미반영(확인필요)"}
    return Command(update={"parking_req": pr, "citations": [cite], "_toolcalls": ["parking_quota"],
                           "messages": [_tm(f"부설주차 {spaces}대 (시설면적 {floor_area}㎡ ÷ 기준 {base_area_m2}㎡/대 = {raw:.2f}→비고6)", tool_call_id)]})


@tool
def levy_estimate(levy_type: str, land_price: Optional[float] = None, area_m2: Optional[float] = None,
                  rate_pct: Optional[float] = None, *,
                  tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """부담금 추정(법 산식만, 결정적). 단가·율이 없으면 금액 미산출+확인필요(날조 금지).
    농지보전부담금 = 개별공시지가 × 율% × 면적 [농지법§38·시행령§53①; **rate_pct는 LLM이 §53서 읽어 전달 — 농업진흥지역 안/밖으로 율이 갈리니 원문 확인(예시값 안 박음)**]. ㎡당 상한 5만원(시행규칙§47의2)은 법정상한 상수로 적용.
    대체산림자원조성비 = 면적 × 산림청 고시단가 [**단가 데이터원 없음→금액 미산출, 확인필요**].
    개발부담금 = 종료시점지가−개시시점지가−정상상승분−개발비용 [**설계前 산정 구조적 불가→부과대상·근거조문만**].
    도구는 용도지역→율, 연도→단가 같은 하드코딩 없음 — 값은 전부 인자."""
    lt = _S(levy_type)
    if "농지" in lt:
        formula = "개별공시지가 × 율% × 면적(㎡당 5만원 상한)"
        if land_price and area_m2 and rate_pct:
            amt = int(land_price * (rate_pct / 100.0) * area_m2)
            cap = int(50000 * area_m2)   # 시행규칙§47의2 ㎡당 5만원 상한
            capped = amt > cap
            amt = min(amt, cap)
            li = LevyItem(levy_type="농지보전부담금", formula=formula, amount=amt, status="산출",
                          note=f"공시지가 {int(land_price)}×{rate_pct}%×{area_m2}㎡" + ("(5만원/㎡ 상한 적용)" if capped else ""),
                          citation=Citation(source="law", law_name="농지법", article="§38·시행령§53①",
                                            quote=f"율 {rate_pct}%(농지법 시행령§53)·㎡당 5만원 상한(시행규칙§47의2)")).model_dump()
            msg = f"농지보전부담금 ≈ {amt:,}원 ({formula}, 율 {rate_pct}%)"
        else:
            li = LevyItem(levy_type="농지보전부담금", formula=formula, status="확인필요",
                          note="율(rate_pct=진흥30/밖20)·공시지가·면적 필요 — 시행령§53서 율 읽어 재호출").model_dump()
            msg = "농지보전부담금: 산식만(율·공시지가·면적 필요)"
    elif "산림" in lt or "대체" in lt:
        li = LevyItem(levy_type="대체산림자원조성비", formula="면적 × 산림청 고시단가(보전+30%/제한+100% 할증)",
                      status="확인필요", note="단가=산림청 매년 고시(법령·API 밖) → 금액 미산출",
                      citation=Citation(source="law", law_name="산지관리법", article="§19",
                                        quote="대체산림자원조성비 산식 — ㎡당 단가는 산림청 고시 확인필요")).model_dump()
        msg = "대체산림자원조성비: 산식만 — 단가 데이터원 없음(확인필요)"
    elif "개발" in lt:
        li = LevyItem(levy_type="개발부담금", formula="종료시점지가−개시시점지가−정상상승분−개발비용",
                      status="확인필요", note="준공後 감정 구조 → 설계前 금액 산정 불가. 부과대상·근거조문만",
                      citation=Citation(source="law", law_name="개발이익환수법", article="§5·§8",
                                        quote="개발부담금 부과대상·산식 — 종료시점 감정 전 금액 산정 불가")).model_dump()
        msg = "개발부담금: 부과대상·근거조문만(설계前 금액 불가)"
    else:
        li = LevyItem(levy_type=lt or "부담금", formula="", status="확인필요", note="미지원 부담금 유형").model_dump()
        msg = f"부담금 '{lt}': 확인필요"
    upd = {"levies": [li], "_toolcalls": ["levy_estimate"], "messages": [_tm(msg, tool_call_id)]}
    if li.get("citation"):
        upd["citations"] = [li["citation"]]
    return Command(update=upd)


@tool
def author_rule_tool(floor_area: float, work_type: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """작성주체(건축사 필수 여부). 건축법 §23① 원칙·단서를 라이브 fetch해 원문(grounding)을 반환.
    면제(비건축사 가능)는 §23① 단서의 좁은 예외(소규모 증축·대수선 등) — 단서 원문을 읽고 이 케이스가 면제에 해당하는지는 네가 판단하라.
    requires_architect는 fail-closed로 기본 '필수'(True); 단서 면제에 명확히 해당하면 네 서술로 그 근거(어느 호·면적)를 밝혀라."""
    a = RM.author_rule(int(floor_area), work_type or "신축")
    if a.get("상태") == "확인필요":   # §23① fetch 실패 → 기권(fail-closed, 날조 금지)
        return Command(update={"abstentions": [{"node": "author_rule_tool", "사유": a.get("사유", "§23① 미확보")}],
                               "_toolcalls": ["author_rule_tool"],
                               "messages": [_tm("작성주체: §23① 원문 미확보 → 확인필요", tool_call_id)]})
    # 가부 단정 없음 — 원칙·단서 원문만 grounding. requires_architect는 fail-closed 기본 True(면제 판단은 LLM이 단서 원문 대조).
    au = AuthorRule(requires_architect=True, reason=a["사유"]).model_dump()
    cite = Citation(source="law", law_name="건축법", article="§23①", quote=a.get("원칙", "")[:200]).model_dump()
    proviso = " / ".join(a.get("단서", [])) or "(단서 없음)"
    return Command(update={"author": au, "citations": [cite], "_toolcalls": ["author_rule_tool"],
                           "messages": [_tm(f"작성주체 §23① — 원칙: {a.get('원칙','')[:120]} | 단서(면제호): {proviso[:400]} | 케이스: {work_type or '신축'} {int(floor_area)}㎡(면제 해당여부는 단서 원문 대조로 판단)", tool_call_id)]})


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
def record_ordinance_ruling(
        verdict: Annotated[Literal["가능", "불가", "확인필요"], Field(
            description="조례 별표 호목해소 결론. 가능=제공된 별표 원문 호목이 해당 용도를 명시적으로 허용. "
                        "불가=원문이 명시적으로 금지. 확인필요=별표 본문 미확보·호목 참조 미해소·근거 불충분 등 판단 불가(기본값, 기권).")],
        hojeok_path: str, cited_count: int,
        tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """agent 멀티홉 호목해소 결론 커밋. verdict는 위 3개 enum 중 하나만(자유서술 금지).
    환각가드는 build_reasoning(basis)·route(citations==0→abstain)가 담당 — 여기선 LLM이 커밋한 enum을 그대로 기록."""
    return Command(update={"jorye_verdicts": [JoryeVerdict(verdict=verdict, reason=hojeok_path[:200]).model_dump()],
                           "_toolcalls": ["record_ordinance_ruling"],
                           "messages": [_tm(f"조례판정 기록: {verdict} ({hojeok_path})", tool_call_id)]})


@tool
def request_human_input(question: str, fields: list, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """사용자 확정 입력 요청(연면적·층수·용도). interrupt로 중단→Command(resume) 재개. 부록 G2.2."""
    from langgraph.types import interrupt
    ans = interrupt({"type": "need_input", "question": question, "fields": fields})
    if isinstance(ans, dict) and ans.get("type") == "reject":
        return Command(update={"terminal_reason": "aborted", "_toolcalls": ["request_human_input"],
                               "messages": [_tm("사용자 중단", tool_call_id)]})
    upd = {"_toolcalls": ["request_human_input"], "messages": [_tm(f"사용자 입력: {ans}", tool_call_id)]}
    for k in ("floor_area", "floor_count", "use_type"):   # 알려진 상태필드만 충전(숫자는 형변환). 그 외 임의 응답은 위 메시지로 LLM이 읽음
        if isinstance(ans, dict) and k in ans and ans[k] not in (None, ""):
            v = ans[k]
            if k in ("floor_area", "floor_count"):
                try:
                    v = float(v) if k == "floor_area" else int(float(v))
                except (TypeError, ValueError):
                    continue
            upd[k] = v
    return Command(update=upd)


TOOLS = [geocode, get_parcel, get_land_use, get_land_price, act_landuse,
         ordin_byeolpyo_fetch, law_byeolpyo_fetch, law_article_fetch, docs_for_stage, compute_scale,
         compute_envelope, parking_quota, levy_estimate,
         author_rule_tool, reg_effect_resolve_tool, record_uijae, record_ordinance_ruling,
         request_human_input]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}
