# -*- coding: utf-8 -*-
"""ReAct 도구 — 검증된 research/wf_*.py를 @tool로 래핑. 부록 G2.1: Command(update) 반환.
사실=tool fetch(원문), 인용 동반, 못 얻으면 확인필요. 내부 로직 전부 실증(wf_*.py)."""
import sys, re, io, zlib, json, urllib.request, urllib.parse, time, uuid, datetime
from typing import Annotated, Optional, List, Literal
from pydantic import Field
from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "lawlib"))   # 통합: research→lawlib(상대경로)
import law_fetch as L            # search/service/ordin_search/ordin_service (실증)
import wf_e2e_live as W          # geo/parcel/ned/act/dig (실증 VWorld+행위제한)
import wf_docs_agent as DOC      # docs_for (시행규칙 조문 호 전수)
import wf_reg_agent as REG       # resolve (규제명→법령조회)
import wf_roadmap as RM          # author_rule (건축법§23①)
from state import Citation, UijaeItem, DocItem, StageDocs, JoryeVerdict, VerdictLabel, RegEffect, AuthorRule, ScaleLimit, LevyItem
import math

# 지목 28종 부호→정식명 전수(공간정보관리법 시행령 §58). VWorld jibun이 부호 1자만 줄 때 정규화 — 부분매핑 desync 방지.
# (정식명 토큰은 키가 아니므로 .get(t,t)로 그대로 통과 = 이미 정규형. 의제·부담금 유형 결정은 LLM 위임.)
_JIMOK = {"전": "전", "답": "답", "과": "과수원", "목": "목장용지", "임": "임야",
          "광": "광천지", "염": "염전", "대": "대", "장": "공장용지", "학": "학교용지",
          "차": "주차장", "주": "주유소용지", "창": "창고용지", "도": "도로", "철": "철도용지",
          "제": "제방", "천": "하천", "구": "구거", "유": "유지", "양": "양어장",
          "수": "수도용지", "공": "공원", "체": "체육용지", "원": "유원지", "종": "종교용지",
          "사": "사적지", "묘": "묘지", "잡": "잡종지"}
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
    cite = Citation(source="vworld", title="지적(필지) 정보 — 국토교통부 연속지적도",
                    quote=f"지목 {jimok}" + (f", 도로접면 {road}" if road else "")).model_dump()
    return Command(update={"pnu": pnu, "area_cd": pnu[:5], "jimok": jimok, "sigungu": sigungu,
                           "road_side": road, "citations": [cite], "_toolcalls": ["get_parcel"],
                           "messages": [_tm(f"PNU={pnu} 행정코드={pnu[:5]} 지목={jimok} 도로접면={road} 시군구={sigungu} ({addr})", tool_call_id)]})


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
    upd = {"zone": zone, "zone_ucodes": uq, "reg_overlaps": regs,
           "_toolcalls": ["get_land_use"],
           "messages": [_tm(f"용도지역={zone} 대지면적={land_area}㎡ 도로접면={road} UQ(전부 콤마로 이어 act_landuse에 그대로)={','.join(uq)} 규제={regs}", tool_call_id)]}
    if road is not None:   # 도로접면 None이면 get_parcel이 잡은 값(맹지 등)을 덮어쓰지 않음 — 맹지 fail-closed 보존(last-write-wins 버그 차단)
        upd["road_side"] = road
    if land_area is not None:
        upd["land_area"] = land_area
    if zone is None:   # 용도지역은 모든 필지에 존재 → None=NED 조회 실패(정당한 빈결과 아님), 정직 기권(검수 EB-3)
        upd["abstentions"] = [{"node": "get_land_use", "사유": "용도지역 미확보(VWorld NED 빈응답/실패) — 직접 확인 필요"}]
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
    입력: zone_ucode=get_land_use의 UQ코드 **전부를 콤마로 이어** 그대로(예 UQA001,UQA121 — 상위 generic 코드는 빈값이라 API가 specific 코드에서 행위제한 회수). use_type=**건축법 별표1의 가장 구체적인 세목 시설명**(사용자 표현을 그 세목명으로 해석 — 예 카페→일반음식점, 사무실→업무시설, 다세대→공동주택). **주의: 이 API는 시설명을 부분문자열로 매칭한다** → 넓은 상위분류('운동시설')로 질의하면 엉뚱한 세목('가축용 운동시설')이 substring으로 잡힐 수 있다. 반드시 구체 세목으로 질의하고, 반환된 시설명(NODE_DESC)이 의도한 시설과 다르면 그 결과를 근거로 쓰지 말고 별표1 호목으로 직접 해소하라. area_cd=get_parcel의 area_cd(PNU 앞5).
    반환 act_verdict∈{가능(법령직접), 조례확인필요(혼재), 조례확인필요(조건부), 조례확인필요}. 빈값·혼재·조건부=조례위임(_delegated=True) → 단정 말고 ordin_byeolpyo_fetch로 진행."""
    det = W.act_detail(zone_ucode, use_type, area_cd)   # item별 reg+근거조항+시설명 — act가 버리던 근거 보존
    rg = [d["reg"] for d in det]                          # 가부 신호(REG_NM=API 자체 판정 enum; 도구는 읽기만, 단정 아님)
    # REG_NM(API 자체판정 enum={가능,금지,조건,빈값}) 정밀독 — 값 그대로 읽음(도구는 enum 읽기만, 단정 아님).
    has_y = any("가능" in x for x in rg)      # '가능'
    has_n = any("금지" in x for x in rg)      # '금지'=부정/조례위임
    has_cond = any("조건" in x for x in rg)   # '조건'=조건부 건축(별표서 조건 확인)
    if has_y and not has_n and not has_cond:
        v, dele = "가능(법령직접)", False
    elif has_y and has_n:
        v, dele = "조례확인필요(혼재)", True    # 가능·금지 혼재 → 단정 금지
    elif has_cond:
        v, dele = "조례확인필요(조건부)", True   # 조건 → 조례·별표서 조건 확인(단정 금지)
    elif has_n:
        v, dele = "조례확인필요", True          # 금지=입지제한/조례위임 가능성
    else:
        v, dele = "조례확인필요", True          # 빈값=조례 위임
    # 인용 정리: 같은 (조항·시설)끼리 묶어 중복 UQ코드 제거 + 가능/금지 혼재(용도지역 중첩)는 한 줄로 정직 표기
    _grp = {}                                    # (ref_law,node) → set(reg)
    for d in det:
        if d.get("ref_law"):
            _grp.setdefault((d["ref_law"], d.get("node", "")), set()).add(d["reg"])
    cites = []
    for (ref_law, node), regs in _grp.items():
        q = (f"{node} → 가능·금지 혼재(용도지역 중첩)"
             if any("가능" in r for r in regs) and any("금지" in r for r in regs)
             else f"{node} → {'/'.join(sorted(regs))}")
        cites.append(Citation(source="data", law_name="행위제한(국토부 1613000)", article=ref_law, quote=q).model_dump())
    detail = " / ".join(f"{d.get('node', '')}={d['reg']}({d.get('ref_law', '')})" for d in det) or "빈값"
    upd = {"act_verdict": v, "act_reg_raw": rg, "_delegated": dele,
           "citations": cites, "_toolcalls": ["act_landuse"],
           "messages": [_tm(f"행위제한 {use_type}@{zone_ucode}: {detail} → {v}", tool_call_id)]}
    if not det:   # 직접근거 0 — API 빈응답/세목 불일치/조례위임 구분불가 → 정직 기권(트레이스 '확보' 오표기 방지, 검수 EB-2)
        upd["abstentions"] = [{"node": "act_landuse", "사유": f"행위제한 직접 근거 없음({use_type}) — 조례로 확인 필요"}]
    return Command(update=upd)


# ── 조례 별표 BodyText (멀티홉 1번째 홉) ─────────────────────
def _mark_trunc(cite, full_len, cap, offset=0):
    """Citation에 truncation 메타 — 캡 산술만(본문 의미 0). truncated=이 창(offset~offset+cap) 뒤에 더 있나(offset+cap<full), read_coverage=여기까지 읽은 비율. source_id=law_name|article(U5)."""
    cite["source_id"] = f"{cite.get('law_name', '')}|{cite.get('article', '')}"
    cite["truncated"] = (offset + cap) < full_len
    cite["read_coverage"] = round(min(offset + cap, full_len) / full_len, 3) if full_len else 1.0
    return cite


def _nows(x): return re.sub(r"\s+", "", _S(x))         # 공백 무시 비교(별표제목 '제1종 일반' vs zone '제1종일반')

def _byeolpyo_units(j):
    bu = j.get("별표", {}).get("별표단위") if isinstance(j.get("별표"), dict) else None
    if not bu: bu = j.get("별표단위")                    # 응답변형: 별표단위가 j 최상위(서울 등 특별·광역시)
    if isinstance(bu, dict): bu = [bu]
    return bu or []

def _pick_zone_byeolpyo(units, zone):
    zk = _nows(zone)
    for b in units:                                     # zone+건축가능/불가 든 별표(공백무시 매칭)
        if not isinstance(b, dict): continue
        t = _nows(b.get("별표제목"))
        if zk in t and ("건축할수있는" in t or "건축할수없는" in t):
            return b
    return None

def _byeolpyo_body(b):
    inline = _S(b.get("별표내용")).strip()                # inline 우선(특별·광역시 시 조례는 별표내용에 본문)
    if inline:
        return re.sub(r"\s+", " ", inline).strip()
    url = _S(b.get("별표첨부파일명"))                      # 폴백: 첨부파일(.hwp/.hwpx — 도 산하 시·군은 inline 비고 본문 첨부)
    if not url: return None
    raw = None
    for _ in range(4):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Connection": "close"}), timeout=40).read(); break
        except Exception:
            time.sleep(1.5)
    full = L.byeolpyo_text(raw)                          # .hwp(PARA_TEXT 레코드)·.hwpx 자동 — 통째 utf-16 디코드 쓰레기 방지
    return re.sub(r"\s+", " ", full).strip() if full else None

def _search_zone_byeolpyo(query, locality, zone):
    """query로 조례 검색 → locality 든 후보(광역 단위 조례 우선) 중 zone 별표 본문을 찾으면 (본문, meta, 광역명)."""
    cands = [it for it in (L.ordin_search(query).get("items") or []) if (not locality or locality in _S(it.get("자치법규명")))]
    cands.sort(key=lambda it: 0 if _nows(it.get("지자체기관명")) == _nows(locality) else 1)   # 광역(시·도) 단위 조례 먼저
    last_nm = ""; wide = ""
    for it in cands:
        nm = _S(it.get("자치법규명"))
        last_nm = nm
        wide = wide or (_S(it.get("지자체기관명")).split() or [""])[0]   # 후보 기관명 첫 토큰=광역명(폴백 키)
        b = _pick_zone_byeolpyo(_byeolpyo_units(L.ordin_service(it.get("자치법규일련번호") or it.get("MST"))), zone)
        if not b: continue
        body = _byeolpyo_body(b)
        if not body: continue
        return body, {"조례명": nm, "별표": _S(b.get("별표번호")) + " " + _S(b.get("별표제목"))[:30]}, wide
    return None, {"조례명": last_nm}, wide

def _ordin_bodytext(sigungu, zone):
    body, meta, wide = _search_zone_byeolpyo(f"{sigungu} 도시계획", sigungu, zone)   # 1차: sigungu 그대로(도 산하 시·군)
    if body:
        return body, meta
    toks = _S(sigungu).split()                          # 2차: 광역 폴백 — 자치구는 zone 별표를 시 단위 조례에 위임
    wide_nm = toks[0] if len(toks) >= 2 else wide        # '서울특별시 강남구'→광역토큰; 단일토큰이면 후보 기관명서 유도
    if wide_nm and wide_nm != sigungu:
        body, meta2, _ = _search_zone_byeolpyo(f"{wide_nm} 도시계획", wide_nm, zone)
        if body:
            return body, meta2
    return None, meta


@tool
def ordin_byeolpyo_fetch(sigungu: str, zone: str, tool_call_id: Annotated[str, InjectedToolCallId], area_cd: str = "", offset: Annotated[int, Field(description="긴 별표 본문 이어읽기 시작 위치(문자). 기본 0. ToolMessage가 'offset=N' 알려주면 그 값으로 재호출해 다음 부분 읽기.")] = 0) -> Command:
    """지자체 도시계획조례 '{zone} 건축가능 별표' BodyText. 사전인덱스 HIT 우선→MISS면 라이브 추출. 멀티홉 1홉. area_cd(get_parcel의 행정코드5)를 주면 같은 zone명이 여러 지자체에 겹쳐도 정확매칭(없으면 시군구명 폴백)."""
    # 가늠터 RAG: 사전인덱싱 HIT-first (infra 미연결/MISS/예외면 조용히 라이브 폴백 — Command 형태 불변)
    try:
        from infra.ordin_rag import lookup_ordin
        hit = lookup_ordin(sigungu, zone, area_cd)
    except Exception:
        hit = None
    if hit:
        body = hit["body"]
        art = f"{hit['byeolpyo_no']} {str(hit['byeolpyo_title'])[:30]}"
        cite = Citation(source="ordin", law_name=hit["ordin_name"], article=art,
                        quote=body[:110], extract_method="인덱스청크").model_dump()
        cite = _mark_trunc(cite, len(body), 12000, offset)
        return Command(update={"citations": [cite], "_delegated": True, "doc_index_hit": True,
                               "_toolcalls": ["ordin_byeolpyo_fetch"],
                               "messages": [_tm(f"[조례 별표 BodyText(인덱스):{art}] (근거ID:{cite['source_id']})\n{body[offset:offset+12000]}" + ("" if (offset + 12000) >= len(body) else f"\n\n…[{len(body)}자 중 {offset}~{offset+12000}자 표시. 이후 {len(body)-(offset+12000)}자 더 — 같은 인자에 offset={offset+12000} 넣어 이어읽어라(끝까지 안 읽고 단정하면 강등). 못 찾으면 확인필요]"), tool_call_id)]})
    # ── 라이브 폴백(기존 경로 — 불변) ──
    text, meta = _ordin_bodytext(sigungu, zone)
    if not text:
        return Command(update={"jorye_verdicts": [JoryeVerdict(ordin_name=meta.get("조례명"), verdict="확인필요",
                               reason="별표 추출 실패(미인덱싱/hwpx)").model_dump()],
                               "doc_index_hit": False, "_toolcalls": ["ordin_byeolpyo_fetch"],
                               "messages": [_tm(f"조례 별표 추출 실패: {meta}. → law_byeolpyo_fetch로 건축법 시행령 별표1을 직접 조회해 호목 해소를 시도하고, 끝내 못 얻으면 확인필요로 둬라.", tool_call_id)]})
    cite = Citation(source="ordin", law_name=meta["조례명"], article=meta["별표"], quote=text[:110],
                    extract_method="BodyText").model_dump()
    # 멀티홉 본문을 ToolMessage로 → (실 LLM) agent가 호목참조 읽고 다음 홉 결정
    cite = _mark_trunc(cite, len(text), 12000, offset)
    return Command(update={"citations": [cite], "_delegated": True, "doc_index_hit": False, "_toolcalls": ["ordin_byeolpyo_fetch"],
                           "messages": [_tm(f"[조례 별표 BodyText:{meta['별표']}] (근거ID:{cite['source_id']})\n{text[offset:offset+12000]}" + ("" if (offset + 12000) >= len(text) else f"\n\n…[{len(text)}자 중 {offset}~{offset+12000}자 표시. 이후 {len(text)-(offset+12000)}자 더 — 같은 인자에 offset={offset+12000} 넣어 이어읽어라(끝까지 안 읽고 단정하면 강등). 못 찾으면 확인필요]"), tool_call_id)]})


@tool
def law_byeolpyo_fetch(law_name: str, byeolpyo_kw: str, tool_call_id: Annotated[str, InjectedToolCallId], offset: Annotated[int, Field(description="긴 별표 본문 이어읽기 시작 위치(문자). 기본 0. ToolMessage가 'offset=N' 알려주면 그 값으로 재호출해 다음 부분 읽기.")] = 0) -> Command:
    """국가법령(본법/시행령/시행규칙)의 별표 inline 텍스트(원문 전체). 어느 법이든.
    입력: law_name=법령명(안 맞으면 후보 목록 반환→재시도). byeolpyo_kw=별표 번호('1') 또는 제목 키워드('용도별').
    별표 본문 전체를 반환하니(예 건축법 시행령 별표1 용도분류 ~11k자), 네가 원문을 직접 읽어 해당 호목·용도 포함 여부를 끝까지 확인하라.
    용도: 조례 별표가 가리킨 국가법령 별표 해소(호목 멀티홉), 또는 행위제한이 특정 법령에 있을 때 그 법의 별표 직접 조회."""
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
        if (numkey and numkey == bno) or (byeolpyo_kw.strip() and byeolpyo_kw.strip() in bti):   # 번호 또는 제목 부분문자열(입력기반 일반규칙만)
            t = re.sub(r"\s+", " ", _S(b.get("별표내용")))
            _bno = _S(b.get("별표번호")).lstrip("0") or "1"   # "0001"→"1"(표시용)
            # 인용 quote는 별표 '제목'만(전체 호 raw dump 금지 — 핵심 호목 근거는 조례 판정 인용이 제공)
            cite = _mark_trunc(Citation(source="law", law_name=law_name, article=f"별표 {_bno}", quote=_S(b.get("별표제목"))[:60]).model_dump(), len(t), 20000, offset)
            body = t[offset:offset+20000]   # 별표 본문 창(건축법 별표1 ~11k자 — 보통 한 창에 다 들어옴). 호 파싱 휴리스틱 안 씀, LLM이 원문 직접 읽음
            tail = "" if (offset + 20000) >= len(t) else f"\n\n…[{len(t)}자 중 {offset}~{offset+20000}자 표시. 이후 {len(t)-(offset+20000)}자 더 — 같은 인자에 offset={offset+20000} 넣어 이어읽거나 더 좁은 별표 번호/제목으로 재호출. 끝까지 안 읽고 단정하면 강등, 못 찾으면 확인필요]"
            return Command(update={"citations": [cite], "_toolcalls": ["law_byeolpyo_fetch"],
                                   "messages": [_tm(f"[{law_name} {byeolpyo_kw}] (근거ID:{cite['source_id']})\n{body}{tail}", tool_call_id)]})
    cands = [(_S(b.get("별표번호")), _S(b.get("별표제목"))[:30]) for b in bu if isinstance(b, dict)]   # 형제(law_article_fetch)와 동일 — 후보 돌려줘 LLM 재호출
    return Command(update={"_toolcalls": ["law_byeolpyo_fetch"],
                           "messages": [_tm(f"별표 못찾음. '{law_name}' 별표 후보: {cands}. 정확한 번호나 제목으로 재호출.", tool_call_id)]})


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
def law_article_fetch(law_name: str, article: str, tool_call_id: Annotated[str, InjectedToolCallId], offset: Annotated[int, Field(description="긴 조문 이어읽기 시작 위치(문자). 기본 0. ToolMessage가 'offset=N' 알려주면 그 값으로 재호출해 다음 부분 읽기.")] = 0) -> Command:
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
        cite = _mark_trunc(Citation(source="law", law_name=law_name, article=f"{label}({title})" if title else label,
                        quote=full[:200]).model_dump(), len(full), 7000, offset)
        return Command(update={"citations": [cite], "_toolcalls": ["law_article_fetch"],
                               "messages": [_tm(f"[{law_name} {label}{('('+title+')') if title else ''}] (근거ID:{cite['source_id']})\n{full[offset:offset+7000]}" + ("" if (offset + 7000) >= len(full) else f"\n\n…[{len(full)}자 중 {offset}~{offset+7000}자 표시. 이후 {len(full)-(offset+7000)}자 더 — 같은 인자에 offset={offset+7000} 넣어 이어읽거나 항·호를 좁혀 재호출. 끝까지 안 읽고 단정하면 강등, 못 찾으면 확인필요]"), tool_call_id)]})
    return Command(update={"_toolcalls": ["law_article_fetch"],
                           "messages": [_tm(f"'{law_name}' 제{jono}조{('의'+branch) if branch else ''} 조문 못찾음(번호 확인 후 재시도).", tool_call_id)]})


# ── 서류·규모·작성주체 ───────────────────────────────────────
@tool
def docs_for_stage(stage_key: str, when_note: str = "", author_note: str = "", law_name: str = "", article: str = "", hang: str = "", *, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """단계별 시행규칙 첨부서류 호 전수(누락0).
    stage_key: work_type에 맞는 단계명 — 신축이면 '건축허가'·'착공신고'·'사용승인'; 용도변경이면 '용도변경'; 대수선이면 '대수선'; + 의제 stage_key(농지전용/산지전용/개발행위 등). placeholder 금지.
    law_name·article: 그 단계 첨부서류 시행규칙 조문을 지정 — law_name(시행규칙명, 예 '건축법 시행규칙')·article(조, 예 '6'·'12의2'). law_article_fetch로 먼저 확인한 값만 전달(기억으로 짓지 말 것). hang: 첨부서류가 특정 항에 있으면 그 항(예 '②') 지정 가능(보통 생략 — 호 있는 첫 항 자동).
    when_note: 이 단계를 '언제' 하는지 한 줄(예 '공사 착수 직전 신고', '완료 후 사용 전 신청'). 건축법 절차 근거로 생성. 의제 단계면 '건축허가 시 함께 의제처리'. 모르면 빈 문자열.
    author_note: 작성주체를 법령근거로 한 줄(예 '신청인 본인; 설계도서는 건축사-건축법§23'·'감리완료보고서는 감리자-§25'). 법으로 판단(키워드 추측 금지). 모르면 빈 문자열."""
    r = DOC.docs_for(stage_key, law_name=law_name or None, article=article or None, hang_override=hang or None)
    if r["상태"] != "전수확보":
        return Command(update={"documents": [StageDocs(stage_key=stage_key, status="확인필요").model_dump()],
                               "_toolcalls": ["docs_for_stage"], "messages": [_tm(f"{stage_key} 서류 확인필요", tool_call_id)]})
    items = [DocItem(ho=d["호"], doc_name=d["서류"], has_proviso=d["단서있음"],
                     conditional=d.get("조건부", False), item_type=d.get("유형", "doc"),
                     form_title=(d.get("서식") or {}).get("제목", ""),
                     form_hwp=(d.get("서식") or {}).get("hwp", ""),
                     form_pdf=(d.get("서식") or {}).get("pdf", "")).model_dump() for d in r["서류"]]
    af = r.get("신청서") or {}
    sd = StageDocs(stage_key=stage_key, law=r["법령"], article=r["조"], count=r["건수"],
                   when_note=when_note, when_law=r.get("when_law", ""), when_title=r.get("when_title", ""),
                   when_quote=r.get("when_quote", ""), author_note=author_note,
                   apply_title=af.get("제목", ""), apply_hwp=af.get("hwp", ""), apply_pdf=af.get("pdf", ""),
                   items=items).model_dump()
    # 조건부(해당시만 제출) 최상위 호만 추출 — 에이전트가 케이스로 판정하도록 ToolMessage에 노출(목은 부모 호에 포함)
    cond_top = [f"{it['ho']} {it['doc_name'][:24]}" for it in items
                if it.get("conditional") and not any(c in it["ho"] for c in "가나다라마바사아자차카타파하")]
    msg = f"{stage_key} 첨부 {r['건수']}호 전수({r['법령']} {r['조']})"
    if cond_top:
        msg += " · 조건부(해당시만, 케이스 판정 필요 — assess_conditional_docs): " + "; ".join(cond_top)
    return Command(update={"documents": [sd], "_toolcalls": ["docs_for_stage"],
                           "messages": [_tm(msg, tool_call_id)]})


@tool
def assess_conditional_docs(assessments: list, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """조건부('해당 시에만 제출') 서류를 케이스로 판정해 기록(docs_for_stage가 ToolMessage에 알려준 조건부 호마다 1건).
    assessments=[{stage_key, ho, applies, reason}].
      applies: 'yes'(해당=제출 필요) | 'no'(비해당=제출 불요) | 'unknown'(판단불가→확인필요).
      판정법: 이미 확보한 사실(지목·용도지역·의제·면적·소유형태 등)로 판정되면 그걸로 결정. 사용자만 아는 사실(공동소유 여부·사전결정 신청 여부 등)이 필요하면 먼저 request_human_input으로 평이하게 묻고(여러 개면 한 번에 묶어) 그 답으로 판정. 끝내 모르면 'unknown'.
      reason: 판정 근거 한 줄(사용자가 읽을 평이한 말; 법 조문이름 나열 금지)."""
    rows = []
    for a in (assessments or []):
        if not isinstance(a, dict):
            continue
        ap = str(a.get("applies", "unknown")).lower()
        if ap not in ("yes", "no", "unknown"):
            ap = "unknown"
        rows.append({"stage_key": str(a.get("stage_key", "")), "ho": str(a.get("ho", "")),
                     "applies": ap, "reason": str(a.get("reason", ""))[:200]})
    return Command(update={"cond_assessments": rows, "_toolcalls": ["assess_conditional_docs"],
                           "messages": [_tm(f"조건부 서류 {len(rows)}건 판정", tool_call_id)]})


@tool
def explain_terms(notes: list, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """진단에 나오는 전문용어를 '이 케이스 맥락'에 맞춰 평이하게 설명(사용자가 용어에 마우스 올리면 표시).
    notes=[{term, note}]. term=용어(의제·작성주체·건폐율·용적률·형질변경·별표 등), note=이 진단 상황에 맞춘 한두 문장(이미 확보한 사실 근거; 일반 사전정의 말고 '이 땅/이 건물'에 특정). 핵심 2~5개만."""
    d = {}
    for n in (notes or []):
        if isinstance(n, dict) and n.get("term"):
            d[str(n["term"])] = str(n.get("note", ""))[:300]
    return Command(update={"term_notes": d, "_toolcalls": ["explain_terms"],
                           "messages": [_tm(f"용어 {len(d)}개 맥락설명", tool_call_id)]})


@tool
def compute_scale(floor_area: float, floor_count: int, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """연면적/층수→규모상한 결정적 룰(에너지≥500㎡·구조안전≥200㎡ or 2층). 임계값은 결정적 법정상수(계산기라 코드 상존).
    **이 플래그가 켜지면 근거 조문을 law_article_fetch로 직접 인용하라**(코드는 조문을 박지 않음 — 현행 원문에서): 에너지=녹색건축물 조성 지원법 시행령 제10조, 구조안전=건축법 시행령 제32조. 목구조·창고·단독주택 등 예외와 시행일은 원문에서 확인(코드의 임계는 그 예외 미반영=과대상이라 안전이나, 실 해당여부는 원문)."""
    sl = ScaleLimit(energy_saving_required=floor_area >= 500,
                    structural_safety_required=(floor_area >= 200 or floor_count >= 2),
                    notes=[f"연면적 {floor_area}㎡·{floor_count}층"]).model_dump()
    return Command(update={"scale_limits": sl, "_toolcalls": ["compute_scale"],
                           "messages": [_tm(f"규모상한: 에너지={sl['energy_saving_required']} 구조안전={sl['structural_safety_required']}(근거조문은 law_article_fetch로 인용)", tool_call_id)]})


@tool
def compute_envelope(land_area_m2: float, bcr_pct: float, far_pct: float,
                     tool_call_id: Annotated[str, InjectedToolCallId], basis_note: str = "",
                     reference_only: Annotated[bool, Field(description="이 규모가 '참고용 신축 가정 상한'이면 True(예: 용도변경·대수선 — 현재 건물에 직접 적용 아님). 실제 신축이면 False.")] = False,
                     area_scope: Annotated[str, Field(description="이 규모가 적용되는 면적 범위를 평이하게(예 '변경 대상 약 300㎡', '대지 전체 신축'). 비우면 표시 안 함.")] = "") -> Command:
    """건폐율·용적률 → 최대 건축면적·연면적·약식층수(법 산식만, 결정적).
    산식: 최대건축면적=대지면적×건폐율%, 최대연면적=대지면적×용적률%, 약식층수=연면적/건축면적(상한 가늠).
    **bcr_pct(건폐율%)·far_pct(용적률%)는 인자 — LLM이 law_article_fetch로 국토계획법 시행령 §84/§85 또는 도시계획조례서 읽은 실제치를 전달**(도구에 용도지역→율 하드코딩 없음).
    **basis_note(선택)**: 이 가늠의 근거·한계 꼬리표를 LLM이 직접 작성해 전달(코드가 서술 생성 안 함). 예: 용적률을 법정상한 범위로만 읽었으면 '실제치 확인필요', 용도변경이면 '신축 가정 상한·현재는 직접 적용 아님'. 비우면 표시 안 함.
    별도 envelope 키에 저장(scale_limits와 분리 — 병렬 동시쓰기 충돌 방지). reference_only=True면 참고용(신축 가정 상한 — 용도변경·대수선 등 현재 직접 적용 아님), area_scope로 적용 면적범위 표시."""
    max_bldg = round(land_area_m2 * bcr_pct / 100.0, 1)
    max_floor = round(land_area_m2 * far_pct / 100.0, 1)
    approx = round(max_floor / max_bldg, 1) if max_bldg else None
    env = {"max_building_area": max_bldg, "max_floor_area": max_floor, "approx_floors": approx,
           "envelope_note": basis_note or None,
           "reference_only": bool(reference_only), "area_scope": str(area_scope) or None,   # U6: 참고용(신축가정) 여부·적용 면적범위 — LLM이 세팅(코드는 work_type 추론 0), 저장·표시만
           "notes": [f"대지 {land_area_m2}㎡ 건폐율 {bcr_pct}% 용적률 {far_pct}%"]}
    return Command(update={"envelope": env, "_toolcalls": ["compute_envelope"],   # scale_limits와 분리 키 — 병렬 동시쓰기 충돌(InvalidUpdateError) 방지
                           "messages": [_tm(f"envelope: 최대건축면적={max_bldg}㎡ 최대연면적={max_floor}㎡ 약식층수≈{approx} (건폐율{bcr_pct}%·용적률{far_pct}%)", tool_call_id)]})


@tool
def normalize_area(value: float, unit: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """면적 단위 환산(결정적 — LLM 암산 금지). value를 ㎡로 변환해 돌려준다.
    unit이 '평'이면 ×3.3058(법정 계량환산 400/121㎡), '㎡'/'m2'면 그대로. 반환: ㎡값 + 'N㎡(약 M평)' 표시문.
    사용자가 면적을 평으로 답하거나(예 '30평') 표시용 평수가 필요할 때 이걸 써라(직접 곱하지 말 것). 반환된 ㎡값을 compute_scale/compute_envelope/parking_quota 등에 그대로 넘겨라."""
    u = (unit or "").strip().lower()
    m2 = round(value * 3.3058, 2) if u in ("평", "py", "pyeong") else round(float(value), 2)
    pyeong = round(m2 / 3.3058, 1)
    return Command(update={"_toolcalls": ["normalize_area"],
                           "messages": [_tm(f"면적 환산: {value}{unit} → {m2}㎡(약 {pyeong}평)", tool_call_id)]})


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
                          note="율(rate_pct)·공시지가·면적 필요 — 농지법 시행령§53에서 농업진흥지역 안/밖 율을 읽어 재호출(값은 원문에서)").model_dump()
            msg = "농지보전부담금: 산식만(율·공시지가·면적 필요)"
    elif "산림" in lt or "대체" in lt:
        li = LevyItem(levy_type="대체산림자원조성비", formula="면적 × 산림청 고시단가(보전산지/준보전산지 등급별 할증 적용)",
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
    a = RM.author_rule(int(floor_area), work_type)   # 신축 기본 가정 제거(무하드코딩) — 작업유형은 §23① 판정에 안 쓰임(표시용)
    if a.get("상태") == "확인필요":   # §23① fetch 실패 → 기권(fail-closed, 날조 금지)
        return Command(update={"abstentions": [{"node": "author_rule_tool", "사유": a.get("사유", "§23① 미확보")}],
                               "_toolcalls": ["author_rule_tool"],
                               "messages": [_tm("작성주체: §23① 원문 미확보 → 확인필요", tool_call_id)]})
    # 가부 단정 없음 — 원칙·단서 원문만 grounding. requires_architect는 fail-closed 기본 True(면제 판단은 LLM이 단서 원문 대조).
    au = AuthorRule(requires_architect=True, reason=a["사유"]).model_dump()
    cite = Citation(source="law", law_name="건축법", article="§23①", quote=a.get("원칙", "")[:200]).model_dump()
    proviso = " / ".join(a.get("단서", [])) or "(단서 없음)"
    return Command(update={"author": au, "citations": [cite], "_toolcalls": ["author_rule_tool"],
                           "messages": [_tm(f"작성주체 §23① — 원칙: {a.get('원칙','')[:120]} | 단서(면제호): {proviso[:400]} | 케이스: {work_type or '작업유형 미정'} {int(floor_area)}㎡(면제 해당여부는 단서 원문 대조로 판단)", tool_call_id)]})


@tool
def reg_effect_resolve_tool(reg_names: List[str], tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """규제명→근거 법령조문 라이브 조회(시드+검색). resolve(reg_names)."""
    out, eff = REG.resolve(reg_names), []
    for r in out:
        if r["상태"] == "근거확보":
            eff.append(RegEffect(reg_name=r["규제"], law_name=r["법령"], article=r["조"], effect=r["제목"], status="근거확보").model_dump())
        else:   # 미해결(확인필요)도 보존 — 최종 카드서 사라지지 않게 정직 노출(fail-closed)
            eff.append(RegEffect(reg_name=r["규제"], effect=r.get("근거", ""), status="확인필요").model_dump())
    n_ok = sum(1 for r in out if r["상태"] == "근거확보")
    return Command(update={"reg_effects": eff, "_toolcalls": ["reg_effect_resolve_tool"],
                           "messages": [_tm(f"규제효과 {n_ok}건 근거확보·{len(out) - n_ok}건 확인필요(/{len(out)})", tool_call_id)]})


# ── agent 판단 커밋 (record_*) ───────────────────────────────
@tool
def record_uijae(items: list, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """건축허가에 함께 의제처리되는 '별도 인허가'만 커밋(농지전용·산지전용·개발행위·초지전용·사도개설 등 실제 허가/신고). items=[{trigger,permit_name,stage_key}].
    규제중첩·시설지정(도시계획시설·근린공원·개발제한구역·고도지구·정비구역·과밀억제권역 등)은 의제가 아니다 — 여기 기록하지 마라(그건 reg_effect_resolve_tool/유의사항 대상).
    stage_key는 docs_for_stage가 첨부서류를 가져올 수 있는 실제 인허가명이어야 한다(서류가 안 나오는 추상 명칭 금지)."""
    ui = [UijaeItem(**{k: v for k, v in it.items() if k in ("trigger", "permit_name", "stage_key")}).model_dump() for it in items]
    return Command(update={"uijae": ui, "_toolcalls": ["record_uijae"],
                           "messages": [_tm(f"의제 {len(ui)}건 기록", tool_call_id)]})


@tool
def record_reg_resolution(
        reg_name: str,
        status: Annotated[Literal["해소", "미해소", "해당없음", "확인필요"], Field(
            description="이 중첩규제 해소 판정. 해소=법령 근거로 영향없음/충족 확인. 미해소=영향 있어 추가 절차·제한. 해당없음=이 사업과 무관. 확인필요=판단 근거 부족(기본·기권).")],
        blocking_level: Annotated[Literal["critical", "normal", "reference"], Field(
            description="이 규제가 최종 가부에 미치는 차단도. critical=미해소면 신축·진행 자체가 불확실한 핵심 입지제한. normal=일반 절차. reference=참고용.")],
        basis_seq: list, effect: str,
        tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """중첩규제(reg_overlaps) 1건의 해소 판정을 커밋 — reg_effect_resolve_tool로 법령을 fetch한 뒤 그 근거로 '이 사업에 어떤 영향인지'를 네가 판정해 기록. status/blocking_level은 enum만(자유서술 금지).
    환각가드: status='해소' 또는 blocking_level='critical' 단정은 근거(basis_seq≥1) 필수 — 없으면 거부(재호출 유도, record_ordinance_ruling 동형)."""
    seq = [s for s in (basis_seq or []) if isinstance(s, int)]
    if (status == "해소" or blocking_level == "critical") and not seq:
        return Command(update={"_reject_count": 1, "messages": [_tm(
            f"<tool_use_error>'{reg_name}' {status}/{blocking_level} 단정은 근거(basis_seq≥1) 필수. 법령 근거 seq를 달거나 status='확인필요'로 커밋하라.</tool_use_error>", tool_call_id)]})
    eff = RegEffect(reg_name=reg_name, effect=str(effect)[:200], status=status,
                    blocking_level=blocking_level, basis_seq=seq).model_dump()
    return Command(update={"reg_effects": [eff], "_toolcalls": ["record_reg_resolution"], "_reject_count": 0,
                           "messages": [_tm(f"규제해소 기록: {reg_name} → {status}({blocking_level})", tool_call_id)]})


@tool
def record_ordinance_ruling(
        verdict: Annotated[Literal["가능", "불가", "확인필요"], Field(
            description="조례 별표 호목해소 결론. 가능=제공된 별표 원문 호목이 해당 용도를 명시적으로 허용. "
                        "불가=원문이 명시적으로 금지. 확인필요=별표 본문 미확보·호목 참조 미해소·근거 불충분 등 판단 불가(기본값, 기권).")],
        hojeok_path: str, cited_count: int, relied_source_ids: list,
        tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """agent 멀티홉 호목해소 결론 커밋. verdict는 위 3개 enum 중 하나만(자유서술 금지).
    relied_source_ids = 이 판정이 의존한 근거ID들(ToolMessage 머리의 '근거ID:...'를 그대로). 그 근거 별표가 표시한도서 잘렸으면(truncated) '가능/불가' 단정이 자동 강등(확인필요)된다 → 잘린 별표면 더 좁은 번호로 재호출해 전문 확보 후 단정하라.
    환각가드: '가능/불가' 단정은 인용근거(cited_count≥1) 필수(precondition) + build_reasoning(basis·truncated_basis)·route(citations==0→abstain) 다층."""
    if verdict in ("가능", "불가") and cited_count < 1:   # 근거 없는 단정 거부 — 재호출 유도(_toolcalls 안 남겨 retry 열어둠)
        return Command(update={"_reject_count": 1, "messages": [_tm(
            f"<tool_use_error>'{verdict}' 단정은 인용 근거가 필요(cited_count≥1). 별표 원문 호목을 인용해 다시 커밋하거나, 근거 없으면 verdict='확인필요'로 커밋하라.</tool_use_error>", tool_call_id)]})
    _sids = [str(s) for s in (relied_source_ids or []) if s]
    return Command(update={"jorye_verdicts": [JoryeVerdict(verdict=verdict, reason=hojeok_path[:200], relied_source_ids=_sids).model_dump()],
                           "_toolcalls": ["record_ordinance_ruling"], "_reject_count": 0,
                           "messages": [_tm(f"조례판정 기록: {verdict} ({hojeok_path})", tool_call_id)]})


@tool
def request_human_input(question: str, fields: list,
        ask_category: Annotated[Literal["user_fact"], Field(
            description="질문 분류 슬롯 — 'user_fact'(사용자만 아는 사실: 공사범위·권원/소유·주차 실확보·구조변경 여부·work_type 등)만 허용. 보호구역 효과·조례 기준·제출서류·심의 결과처럼 네가 조사(fetch)하거나 관할이 정하는 건 여기서 묻지 마라.")],
        tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """사용자 확정 입력 요청. 물을 건 **사용자가 직접 아는 사실뿐**(용도·연면적·층수·공사범위·권원·주차 실확보·구조변경). ask_category='user_fact' 슬롯을 명시해야 호출 성립(코드는 무엇이 user_fact인지 정의 안 함 — 네가 'user만 아는 사실'임을 단언). 의제·용도분류·토지 별도행위·산지전용·보호구역효과·조례기준 같은 법적 판단/조사대상은 네가 데이터로 결정하고 묻지 마라(심의 결과 같은 관할 재량은 record_verdict 축에 unresolved_by='authority'로). 질문은 **채팅으로 답하게 평이하게** — '아래 중 체크'·폼·법적분류 선택지 전제 금지(선택지가 꼭 필요하면 질문 문장 안에 풀어라). interrupt로 중단→Command(resume) 재개."""
    from langgraph.types import interrupt
    ans = interrupt({"type": "need_input", "question": question, "fields": fields})
    if isinstance(ans, dict) and ans.get("type") == "reject":
        return Command(update={"terminal_reason": "aborted", "_toolcalls": ["request_human_input"],
                               "messages": [_tm("사용자 중단", tool_call_id)]})
    upd = {"_toolcalls": ["request_human_input"], "messages": [_tm(f"사용자 입력: {ans}", tool_call_id)]}
    for k in ("floor_area", "floor_count", "use_type"):   # 알려진 스칼라 상태필드(숫자는 형변환)
        if isinstance(ans, dict) and k in ans and ans[k] not in (None, ""):
            v = ans[k]
            if k in ("floor_area", "floor_count"):
                try:
                    v = float(v) if k == "floor_area" else int(float(v))
                except (TypeError, ValueError):
                    continue
            upd[k] = v
    # 권원·공동소유·사전결정·분할납부 등 '서류 판단용' 답을 document_facts로 구조화 durable 저장(검수 #2: 전엔 floor/use만 저장돼 사라졌음).
    #  키 = 에이전트가 물은 field명(구조화 응답) 또는 'answer'(자유텍스트). assess_conditional_docs·verdict가 참조, 카드 '확인된 사실' 노출.
    facts = {str(k): str(v)[:200] for k, v in (ans.items() if isinstance(ans, dict) else [])
             if k not in ("floor_area", "floor_count", "use_type", "type") and v not in (None, "")}
    if facts:
        upd["document_facts"] = facts
    return Command(update=upd)


@tool
def record_verdict(final_verdict: Annotated[Literal["가능", "가능(조건부)", "위험·금지", "확인필요"], Field(
            description="진단 최종 종합판정 — 4종 중 하나. 모든 축을 종합해 네가 합성.")],
        dimensions: list, basis_seq: list,
        tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """진단 최종판정을 LLM(너)이 합성해 커밋(코드 if/else 판정 대체). 이게 진단의 결론이다.
    dimensions = 이 케이스에서 실제로 가부를 가른 '판정 축'들을 **네가 정해** 나열(고정 목록 아님 — 케이스마다 다름):
      [{dimension: 축 이름(예 '용도'·'접도'·'권원'·'조례'·'의제'·'영업신고' 등 이 사안에 맞게), status: '충족'|'주의'|'확인필요'|'불가', reason: 평이한 한 줄, basis_seq: 근거 citation/step seq들,
        blocking_level: 'critical'(이 축 미충족이면 진행 자체 불가한 핵심축)|'none'(기본), unresolved_by: 'authority'(교육환경·도시계획 등 관할 심의로만 풀림)|'agent'(더 조사하면 풀림)|'user'(사용자 사실확인 필요)|'none'(해소됨)}].
    basis_seq(최상위) = 종합판정의 핵심 근거 seq.
    환각가드: final_verdict가 '가능'/'가능(조건부)'면 basis_seq 필수 + **차단 축(status='불가' 또는 blocking_level='critical' 또는 unresolved_by가 agent/authority)이 있으면 안 됨** — 그런 축 위엔 종합이 '가능'일 수 없음(미해소 핵심축 위 '가능' 금지 → '확인필요'/'위험·금지'로). 특히 관할 심의가 선결(unresolved_by='authority')이면 '가능(조건부)'가 아니라 '확인필요'."""
    dims = [d for d in (dimensions or []) if isinstance(d, dict)]
    # 차단 축 = 불가 OR critical(핵심축 미충족) OR 미해소(agent 더조사·authority 관할심의). 이런 축 위엔 '가능'·'가능(조건부)' 둘 다 못 얹음(완료계약 U3). soft(확인필요)=불확실 축: 무조건'가능'은 막고(가능(조건부)로 낮춤) '가능(조건부)'엔 조건으로 허용. 코드는 LLM-set enum(status/blocking_level/unresolved_by)만 비교, 도메인파싱 0.
    blocked = [d for d in dims if str(d.get("status", "")) == "불가"
               or str(d.get("blocking_level", "")) == "critical"
               or str(d.get("unresolved_by", "none")) in ("agent", "authority")]
    soft = [d for d in dims if str(d.get("status", "")) == "확인필요"]
    bad = blocked + soft if final_verdict == "가능" else blocked
    if final_verdict in ("가능", "가능(조건부)") and (not basis_seq or bad):
        why = "인용 근거(basis_seq)가 없다" if not basis_seq else f"미충족 축({[(d.get('dimension'), d.get('status'), d.get('unresolved_by', 'none')) for d in bad]})이 있는데 종합이 '{final_verdict}'다 — 불가·critical·미해소(agent/authority) 축 위엔 '가능'계열 불가, '확인필요' 축 위엔 무조건'가능' 불가('가능(조건부)'/'확인필요'로)"
        return Command(update={"_reject_count": 1, "messages": [_tm(
            f"<tool_use_error>종합판정 거부: {why}. 근거를 달거나, 막힌 축이 있으면 final_verdict를 '확인필요'/'위험·금지'로 다시 커밋하라.</tool_use_error>", tool_call_id)]})
    def _mk(d):
        st = str(d.get("status", "주의"))
        if st not in ("충족", "주의", "확인필요", "불가"):
            st = "주의"
        bl = str(d.get("blocking_level", "none"))
        if bl not in ("none", "critical"):
            bl = "none"
        ub = str(d.get("unresolved_by", "none"))
        if ub not in ("none", "agent", "authority", "user"):
            ub = "none"
        return VerdictLabel(dimension=str(d.get("dimension", ""))[:40], status=st,
                            reason=str(d.get("reason", ""))[:200],
                            basis_seq=[s for s in (d.get("basis_seq") or []) if isinstance(s, int)],
                            blocking_level=bl, unresolved_by=ub).model_dump()
    labels = [_mk(d) for d in dims]
    return Command(update={"verdict_labels": labels, "_verdict_round": labels, "_llm_verdict": final_verdict, "_toolcalls": ["record_verdict"], "_reject_count": 0,
                           "messages": [_tm(f"종합판정 기록: {final_verdict} (축 {len(labels)}개)", tool_call_id)]})


@tool
def get_building_register(pnu: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """필지(PNU)에 '기존 건물'이 등록돼 있는지 건축물대장으로 확인 → work_type 자동판별. 사용자에게 '빈땅인지/기존건물인지' 묻기 전에 이걸로 먼저 조회하라.
    건물있음=용도변경/대수선 대상(주용도·연면적·층수 반환) · 없음=빈땅 신축 · 조회불가=건축HUB API 활용신청 필요(이땐 빈땅 단정 말고 '미확인'으로 정직하게)."""
    r = W.building_register(pnu)
    b = r.get("건물있음")
    if b is True:
        _ext = "".join([
            f"·기타용도 {r.get('기타용도')}" if r.get('기타용도') else "",
            f"·지하 {r.get('지하층수')}층" if r.get('지하층수') else "",
            f", 구조 {r.get('구조')}" if r.get('구조') else "",
            f", 건폐율 {r.get('건폐율')}%·용적률 {r.get('용적률')}%" if (r.get('건폐율') is not None or r.get('용적률') is not None) else "",
            f", 사용승인일 {r.get('사용승인일')}" if r.get('사용승인일') else "",
        ])
        msg = f"기존 건물 있음 — 주용도 {r.get('주용도')}{_ext}, 연면적 {r.get('연면적')}㎡, 지상 {r.get('지상층수')}층, 동수 {r.get('동수')} → 신축 아님(용도변경/대수선 가능성). 빈땅으로 단정 금지. (as-built 건폐율·용적률·사용승인일·구조는 증축여력·기존불일치 판단 사실 — 네가 해석)"
        fact = f"기존 건물({r.get('주용도')}{_ext})"
    elif b is False:
        msg = f"등록 건축물 없음(빈땅 가능) → 신축 쪽. {r.get('사유','')}"
        fact = "등록 건물 없음(빈땅 가능)"
    else:
        msg = f"건물 존재 여부 미확인 — {r.get('사유','')}. **빈땅으로 단정하지 말 것**(사용자에게 확인하거나 '미확인'으로)."
        fact = "기존 건물 존재 미확인"
    return Command(update={"document_facts": {"기존건물": fact}, "_toolcalls": ["get_building_register"],
                           "messages": [_tm(msg, tool_call_id)]})


@tool
def get_building_floors(pnu: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """기존 건물의 '층별 현재 용도'를 건축물대장 층별개요로 조회 → 용도변경 출발점 확정. get_building_register가 '건물있음'이고 용도변경 쪽일 때 호출(빈땅 신축이면 불필요).
    표제부 주용도(건물 1개)로 갈음 말고, 바꾸려는 층의 현용도를 이걸로 사실확인한 뒤 현용도→목표용도로 건축법§19 변경방향·act_landuse use_type을 정하라."""
    r = W.building_floors(pnu)
    f = r.get("층별있음")
    if f is True:
        lines = []
        for fl in r.get("층목록", []):
            seg = f"{fl.get('층구분') or ''}{fl.get('층') or ''} {fl.get('주용도') or ''}".strip()
            if fl.get("기타용도"): seg += f"({fl.get('기타용도')})"
            if fl.get("면적"): seg += f" {fl.get('면적')}㎡"
            lines.append(seg)
        body = " / ".join([x for x in lines if x])
        msg = f"층별 현재 용도({r.get('행수')}행·{r.get('동수')}동): {body}"
        fact = f"층별 현황: {body}"
    elif f is False:
        msg = f"층별 정보 없음 — {r.get('사유','')}"
        fact = "층별 정보 없음"
    else:
        msg = f"층별개요 조회 불가 — {r.get('사유','')}. 표제부 주용도로 갈음하되 '층별 미확인' 명시."
        fact = "층별 현황 미확인"
    return Command(update={"document_facts": {"층별현황": fact}, "_toolcalls": ["get_building_floors"],
                           "messages": [_tm(msg, tool_call_id)]})


TOOLS = [geocode, get_parcel, get_building_register, get_building_floors, get_land_use, get_land_price, act_landuse,
         ordin_byeolpyo_fetch, law_byeolpyo_fetch, law_article_fetch, docs_for_stage, assess_conditional_docs, explain_terms, compute_scale,
         compute_envelope, normalize_area, parking_quota, levy_estimate,
         author_rule_tool, reg_effect_resolve_tool, record_uijae, record_reg_resolution, record_ordinance_ruling, record_verdict,
         request_human_input]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}
