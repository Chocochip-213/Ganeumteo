# -*- coding: utf-8 -*-
"""ReAct 도구 — 검증된 research/wf_*.py를 @tool로 래핑. 부록 G2.1: Command(update) 반환.
사실=tool fetch(원문), 인용 동반, 못 얻으면 확인필요. 내부 로직 전부 실증(wf_*.py)."""
import sys, re, io, zlib, json, urllib.request, urllib.parse, time, uuid, datetime
from typing import Annotated, Optional, List, Literal
from pydantic import Field
from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.prebuilt import InjectedState   # 결론성 도구 근거계약 검증용(item 0c — state.citations/evidence_records 대조)

from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "lawlib"))   # 통합: research→lawlib(상대경로)
import law_fetch as L            # search/service/ordin_search/ordin_service (실증)
import wf_e2e_live as W          # geo/parcel/ned/act/dig (실증 VWorld+행위제한)
import wf_docs_agent as DOC      # docs_for (시행규칙 조문 호 전수)
import wf_reg_agent as REG       # resolve (규제명→법령조회)
import wf_roadmap as RM          # author_rule (건축법§23①)
import wf_procedure_agent as PROC   # frame (표준 건축행정절차 단계→법조 라우팅 시드)
from state import (Citation, UijaeItem, DocItem, StageDocs, JoryeVerdict, VerdictLabel, RegEffect, AuthorRule, ScaleLimit, LevyItem,
                   EvidenceRecord, BasisClaim, WorkTypeResolution, UseClassification, LanduseResolution, ProcedureStep,
                   collect_evidence_ids, validate_basis_claims, _UNRESOLVED_VALUES)
import math, hashlib


# ── evidence_id 안정키 + EvidenceRecord 적재 (MASTER_PLAN item 0b/0b-2 — 근거계약 토대) ──
def _ev_id(source, head, *parts):
    """안정·결정적 evidence_id. 예 _ev_id('api','act_landuse',pnu,zone,use)→'api:act_landuse|<10hex>'. 같은 입력=같은 ID."""
    key = "|".join(str(p) for p in (head,) + parts)
    return f"{source}:{head}|{hashlib.sha1(key.encode('utf-8','replace')).hexdigest()[:10]}"


def _ev_record(eid, source, raw, **meta):
    """EvidenceRecord dict(state evidence_records에 적재 — quote 실재검증 토대). content_hash 자동, raw 캡 16000(별표 본문 ~12k 커버)."""
    raw = str(raw or "")
    allowed = {k: v for k, v in meta.items() if k in EvidenceRecord.model_fields}
    return EvidenceRecord(evidence_id=eid, source=source, raw_text=raw[:16000],
                          content_hash=hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:16],
                          **allowed).model_dump()


# item 7: 법정 결정상수 provenance(완전제거 아니라 추적 — 어느 법조·기준·확인). 값=계산기 상수로 코드 상존(U7 합의), 출처는 부착.
_STATIC_PROV = {
    "energy_500": (500.0, "녹색건축물 조성 지원법 시행령 제10조"),
    "struct_200": (200.0, "건축법 시행령 제32조"),
    "struct_2f": (2.0, "건축법 시행령 제32조"),
    "nongji_cap_50000": (50000.0, "농지법 시행규칙 제47조의2"),
}
def _static_ev(*const_ids):
    """법정상수 provenance를 evidence_records용 dict로(source='static', claim_type=calculation_basis에만 인용 가능). 현행 원문 확인은 LLM 몫."""
    out = {}
    for cid in const_ids:
        if cid not in _STATIC_PROV:
            continue
        v, law = _STATIC_PROV[cid]
        eid = f"static:{cid}"
        out[eid] = _ev_record(eid, "static", f"{cid}={v} (근거 {law}; 코드 결정상수·현행 원문/시행일 확인 필요)", law_id=law)
    return out

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
def _aslist(v):
    """LLM이 list 인자 자리에 문자열 1개를 주면 글자단위 분해(list('가나')=['가','나']) 방지 — str→[str], None→[], 그 외 iterable→list."""
    if v is None: return []
    if isinstance(v, str): return [v]
    return list(v)


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
    _peid = _ev_id("api", "parcel", pnu)   # item 0b: 필지 EvidenceRecord(지목·도로접면 근거)
    _pmsg = f"지목 {jimok}, 도로접면 {road}, 시군구 {sigungu}, PNU {pnu}"
    cite = Citation(source="vworld", title="지적(필지) 정보 — 국토교통부 연속지적도",
                    quote=f"지목 {jimok}" + (f", 도로접면 {road}" if road else ""), source_id=_peid).model_dump()
    return Command(update={"pnu": pnu, "area_cd": pnu[:5], "jimok": jimok, "sigungu": sigungu,
                           "road_side": road, "citations": [cite], "evidence_records": {_peid: _ev_record(_peid, "api", _pmsg)},
                           "_toolcalls": ["get_parcel"],
                           "messages": [_tm(f"PNU={pnu} 행정코드={pnu[:5]} 지목={jimok} 도로접면={road} 시군구={sigungu} ({addr}) (근거ID:{_peid})", tool_call_id)]})


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
    _leid = _ev_id("api", "land_use", pnu)   # item 0b: 용도지역·규제중첩 EvidenceRecord
    upd = {"zone": zone, "zone_ucodes": uq, "reg_overlaps": regs,
           "evidence_records": {_leid: _ev_record(_leid, "api", f"용도지역 {zone}, 대지면적 {land_area}㎡, 도로접면 {road}, 규제중첩 {regs}")},
           "_toolcalls": ["get_land_use"],
           "messages": [_tm(f"용도지역={zone} 대지면적={land_area}㎡ 도로접면={road} UQ(전부 콤마로 이어 act_landuse에 그대로)={','.join(uq)} 규제={regs} (근거ID:{_leid})", tool_call_id)]}
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
    _pid = _ev_id("api", "land_price", pnu)   # item 0b: 공시지가 EvidenceRecord(부담금 근거)
    upd = {"_toolcalls": ["get_land_price"],
           "evidence_records": {_pid: _ev_record(_pid, "api", f"개별공시지가 {p}원/㎡ (PNU {pnu})")},
           "messages": [_tm(f"공시지가={p}원/㎡ (근거ID:{_pid})", tool_call_id)]}
    if p is not None:
        upd["land_price"] = p
    else:
        upd["abstentions"] = [{"node": "get_land_price", "사유": "공시지가 미확보"}]
    return Command(update=upd)


@tool
def act_landuse(zone_ucode: str, use_type: str, area_cd: str,
                state: Annotated[dict, InjectedState] = None,
                tool_call_id: Annotated[str, InjectedToolCallId] = None) -> Command:
    """행위제한 API **raw 조회**(data.go.kr 1613000) — 코드는 가부를 단정/승격하지 않는다(_delegated=True, item 3).
    **선결**: 먼저 record_use_classification로 생활어(카페/피시방/사무소)를 건축법 시행령 별표1 canonical 세목으로 확정하고, 그 canonical을 use_type으로 넘겨라(코드가 생활어→세목 매핑 안 함).
    입력: zone_ucode=get_land_use UQ코드 전부 콤마결합. use_type=별표1 canonical 세목. area_cd=PNU 앞5.
    **주의: 이 API는 시설명 부분문자열 매칭** → 반환 NODE_DESC가 의도 세목과 다르면 그 결과를 긍정근거로 쓰지 마라. 가능/불가/조건 판정은 NODE_DESC↔intended_use 일치를 네가 확인한 뒤 record_landuse_resolution로 커밋(코드는 raw만 저장)."""
    state = state or {}
    # 선결 가드(item 4): UseClassification 없으면 act 진행 차단(코드가 생활어→세목 매핑 못 함 — LLM이 별표1로 확정 먼저)
    if not [u for u in (state.get("use_classifications") or []) if isinstance(u, dict)]:
        return Command(update={"messages": [_tm(
            "<tool_use_error>act_landuse 선결 미충족: record_use_classification로 생활어→건축법 시행령 별표1 canonical 세목을 먼저 확정하라. 그 canonical 세목을 use_type으로 넘겨라.</tool_use_error>", tool_call_id)]})
    det = W.act_detail(zone_ucode, use_type, area_cd)   # item별 reg+근거조항+시설명(NODE_DESC) — raw evidence 보존
    rg = [d["reg"] for d in det]
    # REG_NM(API 자체판정 enum) 신호만 표기 — 코드는 가부 생성 안 함(가능(법령직접) 승격 제거). 전부 _delegated → LLM이 record_landuse_resolution로 판정.
    has_y = any("가능" in x for x in rg); has_n = any("금지" in x for x in rg); has_cond = any("조건" in x for x in rg)
    raw_signal = f"REG_NM신호 가능={'有' if has_y else '無'}·금지={'有' if has_n else '無'}·조건={'有' if has_cond else '無'}"
    eid = _ev_id("api", "act_landuse", zone_ucode, use_type, area_cd)   # 안정 evidence_id(같은 입력=같은 ID)
    ev = {eid: _ev_record(eid, "api", json.dumps(det, ensure_ascii=False), source_url="data.go.kr/1613000")}
    _grp = {}
    for d in det:
        if d.get("ref_law"):
            _grp.setdefault((d["ref_law"], d.get("node", "")), set()).add(d["reg"])
    cites = []
    for (ref_law, node), regs in _grp.items():
        q = (f"{node} → 가능·금지 혼재(용도지역 중첩)"
             if any("가능" in r for r in regs) and any("금지" in r for r in regs)
             else f"{node} → {'/'.join(sorted(regs))}")
        cites.append(Citation(source="data", law_name="행위제한(국토부 1613000)", article=ref_law, quote=q, source_id=eid).model_dump())
    detail = " / ".join(f"{d.get('node', '')}={d['reg']}({d.get('ref_law', '')})" for d in det) or "빈값"
    upd = {"act_landuse_raw": f"{raw_signal} | {detail}", "act_reg_raw": rg, "_delegated": True,
           "citations": cites, "evidence_records": ev, "_toolcalls": ["act_landuse"],
           "messages": [_tm(f"행위제한 raw {use_type}@{zone_ucode}: {detail} ({raw_signal}) — NODE_DESC↔의도용도 일치 확인 후 record_landuse_resolution로 판정하라(근거ID:{eid})", tool_call_id)]}
    if not det:   # 직접근거 0 — API 빈응답/세목 불일치 → 정직 기권(별표/조례로 확인)
        upd["abstentions"] = [{"node": "act_landuse", "사유": f"행위제한 직접 근거 없음({use_type}) — 별표/조례로 확인 필요"}]
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
    raw = W._dl(url)   # .hwp 첨부 다운로드(4회 지수backoff) — 동일 자작루프 제거, 공통 헬퍼 재사용(검수 REAL-2)
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
        _iev = {cite["source_id"]: _ev_record(cite["source_id"], "ordin", body[offset:offset + 12000], truncated=cite.get("truncated"), read_coverage=cite.get("read_coverage"))}
        return Command(update={"citations": [cite], "evidence_records": _iev, "_delegated": True, "doc_index_hit": True,
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
    _oev = {cite["source_id"]: _ev_record(cite["source_id"], "ordin", text[offset:offset + 12000], truncated=cite.get("truncated"), read_coverage=cite.get("read_coverage"))}   # item 13b: 조례 별표 raw 적재(quote 실재검증)
    return Command(update={"citations": [cite], "evidence_records": _oev, "_delegated": True, "doc_index_hit": False, "_toolcalls": ["ordin_byeolpyo_fetch"],
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
            _bev = {cite["source_id"]: _ev_record(cite["source_id"], "law", body, law_id=law_name, truncated=cite.get("truncated"), read_coverage=cite.get("read_coverage"))}   # item 13b: 법령 별표 raw(별표1 용도분류 등 — quote 실재검증)
            return Command(update={"citations": [cite], "evidence_records": _bev, "_toolcalls": ["law_byeolpyo_fetch"],
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
        _aev = {cite["source_id"]: _ev_record(cite["source_id"], "law", full[offset:offset + 7000], law_id=law_name, truncated=cite.get("truncated"), read_coverage=cite.get("read_coverage"))}   # item 13b: 법령 조문 raw(quote 실재검증)
        return Command(update={"citations": [cite], "evidence_records": _aev, "_toolcalls": ["law_article_fetch"],
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
    if r["상태"] != "전수확보":   # item 5: 미파싱·항불일치 fallback → list_status=확인필요(전수확보 오판 차단)
        return Command(update={"documents": [StageDocs(stage_key=stage_key, list_status="확인필요", status="확인필요").model_dump()],
                               "_toolcalls": ["docs_for_stage"], "messages": [_tm(f"{stage_key} 서류 확인필요({r.get('사유', '')})", tool_call_id)]})
    items = [DocItem(ho=d["호"], doc_name=d["서류"], has_proviso=d["단서있음"],
                     conditional=d.get("조건부", False), item_type=d.get("유형", "doc"),
                     form_title=(d.get("서식") or {}).get("제목", ""),
                     form_hwp=(d.get("서식") or {}).get("hwp", ""),
                     form_pdf=(d.get("서식") or {}).get("pdf", "")).model_dump() for d in r["서류"]]
    af = r.get("신청서") or {}
    sd = StageDocs(stage_key=stage_key, law=r["법령"], article=r["조"], count=r["건수"],
                   when_note=when_note, when_law=r.get("when_law", ""), when_title=r.get("when_title", ""),
                   when_quote=r.get("when_quote", ""), author_note=author_note, list_status="전수확보", status="전수확보",
                   apply_title=af.get("제목", ""), apply_hwp=af.get("hwp", ""), apply_pdf=af.get("pdf", ""),
                   items=items).model_dump()
    # item 6: 문서 출처 EvidenceRecord 적재(절차/verdict가 이 doc 법조를 근거로 인용 가능 — evidence_id=law:<법령>|<조>)
    _deid = _ev_id("law", f"{r['법령']}|{r['조']}", stage_key)
    _drec = {_deid: _ev_record(_deid, "law", " · ".join(f"{d['호']} {d['서류']}" for d in r["서류"]), law_id=r['법령'])}
    # 조건부(해당시만 제출) 최상위 호만 추출 — 에이전트가 케이스로 판정하도록 ToolMessage에 노출(목은 부모 호에 포함)
    cond_top = [f"{it['ho']} {it['doc_name'][:24]}" for it in items
                if it.get("conditional") and not any(c in it["ho"] for c in "가나다라마바사아자차카타파하")]
    msg = f"{stage_key} 첨부 {r['건수']}호 전수({r['법령']} {r['조']})"
    if cond_top:
        msg += " · 조건부(해당시만, 케이스 판정 필요 — assess_conditional_docs): " + "; ".join(cond_top)
    return Command(update={"documents": [sd], "evidence_records": _drec, "_toolcalls": ["docs_for_stage"],
                           "messages": [_tm(msg + f" (근거ID:{_deid})", tool_call_id)]})


@tool
def assess_conditional_docs(assessments: list, state: Annotated[dict, InjectedState] = None,
                            tool_call_id: Annotated[str, InjectedToolCallId] = None) -> Command:
    """조건부('해당 시에만 제출') 서류를 케이스로 판정해 기록(docs_for_stage가 ToolMessage에 알려준 조건부 호마다 1건).
    assessments=[{stage_key, ho, applies, reason, basis_claims, unresolved_by}].
      applies: 'yes'(해당=제출 필요) | 'no'(비해당=제출 불요) | 'unknown'(판단불가→확인필요).
      **비해당(no)은 근거(basis_claims) 필수·실재**(필수서류를 근거 없이 빼면 안 됨 — 없으면 unknown 강등). 해당(yes)은 안전(서류 포함)이라 근거 권장.
      판정법: 확보한 사실(지목·용도지역·의제·면적·소유형태)로 판정. 사용자만 아는 사실이면 request_human_input 먼저. 끝내 모르면 unknown+unresolved_by.
      reason: 평이한 한 줄(법 조문이름 나열 금지)."""
    state = state or {}
    rows = []
    for a in (assessments or []):
        if not isinstance(a, dict):
            continue
        ap = str(a.get("applies", "unknown")).lower()
        if ap not in ("yes", "no", "unknown"):
            ap = "unknown"
        claims = [c for c in (a.get("basis_claims") or []) if isinstance(c, dict)]
        ub = a.get("unresolved_by", "none"); ub = ub if ub in _UNRESOLVED_VALUES else "none"
        if ap == "no":   # 비해당(서류 제외)=결론 → 근거 필수·실재. 없으면 unknown 강등(근거 없는 서류 누락 방지)
            ok, _ = validate_basis_claims(state, claims)
            if not (claims and ok):
                ap = "unknown"
                if ub == "none":
                    ub = "agent"
        if ap == "unknown" and ub == "none":
            ub = "agent"
        rows.append({"stage_key": str(a.get("stage_key", "")), "ho": str(a.get("ho", "")),
                     "applies": ap, "reason": str(a.get("reason", ""))[:200], "unresolved_by": ub, "basis_claims": claims})
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
    _ev = {}   # item 7: 적용된 법정상수 provenance(static:) 적재 — 현행 원문은 LLM이 law_article_fetch로 확인
    if floor_area >= 500:
        _ev.update(_static_ev("energy_500"))
    if floor_area >= 200 or floor_count >= 2:
        _ev.update(_static_ev("struct_200", "struct_2f"))
    return Command(update={"scale_limits": sl, "evidence_records": _ev, "_toolcalls": ["compute_scale"],
                           "messages": [_tm(f"규모상한: 에너지={sl['energy_saving_required']} 구조안전={sl['structural_safety_required']}(근거조문은 law_article_fetch로 인용; 코드 임계 provenance=static)", tool_call_id)]})


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
                  evidence_id: Annotated[str, Field(description="기준면적(base_area_m2)을 읽은 근거 evidence_id — law_byeolpyo_fetch가 ToolMessage 머리에 준 '근거ID:...'. state에 실재해야(임의 값 차단).")] = "",
                  state: Annotated[dict, InjectedState] = None,
                  tool_call_id: Annotated[str, InjectedToolCallId] = None) -> Command:
    """부설주차장 소요대수(법 산식만, 결정적). 소요대수 = ceil_05(시설면적 ÷ 용도별 기준면적). 비고6: 산정 0.5이상→올림 1대.
    **base_area_m2(용도별 기준면적, ㎡/대)는 인자 — LLM이 law_byeolpyo_fetch로 주차장법 시행령 별표1에서 해당 용도의 기준면적을 읽어 전달**(도구에 용도→기준면적 하드코딩 없음). **그 별표1 근거 evidence_id를 함께 전달**(없으면 임의 값 차단·산출 안 함). 조례 강화배율 별도(미반영 시 확인필요)."""
    state = state or {}
    if not base_area_m2 or base_area_m2 <= 0:
        return Command(update={"parking_req": {"status": "확인필요", "note": "기준면적(base_area_m2) 미전달 — 시행령 별표1서 용도별 기준면적 읽어 재호출"},
                               "_toolcalls": ["parking_quota"],
                               "messages": [_tm("부설주차 확인필요: 용도별 기준면적 필요(별표1)", tool_call_id)]})
    if not evidence_id or evidence_id not in collect_evidence_ids(state):   # item 7: 기준면적 값 근거 실재 검증(날조 차단)
        return Command(update={"parking_req": {"status": "확인필요", "note": "기준면적 근거(evidence_id) 미동반/미실재 — 주차장법 별표1 fetch 후 그 근거ID와 함께 재호출"},
                               "_toolcalls": ["parking_quota"],
                               "messages": [_tm("부설주차 확인필요: 기준면적 근거(evidence_id) 필요", tool_call_id)]})
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
                  rate_pct: Optional[float] = None,
                  evidence_id: Annotated[str, Field(description="율(rate_pct)을 읽은 근거 evidence_id(law_article_fetch가 준 '근거ID:...'). 농지 산출엔 필수·실재(임의 율 차단).")] = "",
                  state: Annotated[dict, InjectedState] = None,
                  tool_call_id: Annotated[str, InjectedToolCallId] = None) -> Command:
    """부담금 추정(법 산식만, 결정적). 단가·율이 없으면 금액 미산출+확인필요(날조 금지).
    농지보전부담금 = 개별공시지가 × 율% × 면적 [농지법§38·시행령§53①; **rate_pct는 LLM이 §53서 읽어 전달 — 농업진흥지역 안/밖으로 율이 갈리니 원문 확인. 그 근거 evidence_id 동반(없으면 산출 안 함)**]. ㎡당 상한 5만원(시행규칙§47의2)은 법정상한 상수(provenance=static).
    대체산림자원조성비 = 면적 × 산림청 고시단가 [**단가 데이터원 없음→금액 미산출, 확인필요**].
    개발부담금 = 종료시점지가−개시시점지가−정상상승분−개발비용 [**설계前 산정 구조적 불가→부과대상·근거조문만**].
    도구는 용도지역→율, 연도→단가 같은 하드코딩 없음 — 값은 전부 인자."""
    state = state or {}
    lt = _S(levy_type)
    _lev_static = {}
    if "농지" in lt:
        formula = "개별공시지가 × 율% × 면적(㎡당 5만원 상한)"
        _rate_ok = bool(rate_pct) and bool(evidence_id) and evidence_id in collect_evidence_ids(state)   # item 7: 율 근거 실재 검증
        if land_price and area_m2 and _rate_ok:
            amt = int(land_price * (rate_pct / 100.0) * area_m2)
            cap = int(50000 * area_m2)   # 시행규칙§47의2 ㎡당 5만원 상한(static provenance)
            capped = amt > cap
            amt = min(amt, cap)
            _lev_static = _static_ev("nongji_cap_50000")
            li = LevyItem(levy_type="농지보전부담금", formula=formula, amount=amt, status="산출",
                          note=f"공시지가 {int(land_price)}×{rate_pct}%×{area_m2}㎡" + ("(5만원/㎡ 상한 적용)" if capped else ""),
                          citation=Citation(source="law", law_name="농지법", article="§38·시행령§53①",
                                            quote=f"율 {rate_pct}%(농지법 시행령§53)·㎡당 5만원 상한(시행규칙§47의2)", source_id=evidence_id)).model_dump()
            msg = f"농지보전부담금 ≈ {amt:,}원 ({formula}, 율 {rate_pct}%)"
        else:
            li = LevyItem(levy_type="농지보전부담금", formula=formula, status="확인필요",
                          note="율(rate_pct)·공시지가·면적 + 율 근거 evidence_id 필요 — 농지법 시행령§53에서 농업진흥지역 안/밖 율을 읽어(law_article_fetch) 그 근거ID와 함께 재호출").model_dump()
            msg = "농지보전부담금: 산식만(율·공시지가·면적·근거ID 필요)"
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
    if _lev_static:   # item 7: 5만원 상한 provenance(static) 적재
        upd["evidence_records"] = _lev_static
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
    out, eff, ev = REG.resolve(reg_names), [], {}
    for r in out:
        if r["상태"] == "근거확보":
            # item 13b: reg fetch도 EvidenceRecord 적재(evidence_id=law:법령|조) — record_reg_resolution이 이 근거ID로 basis_claims 인용 가능. raw=조문제목(전문은 law_article_fetch로).
            _eid = _ev_id("law", f"{r['법령']}|{r['조']}", r["규제"])
            ev[_eid] = _ev_record(_eid, "law", str(r.get("제목", "")), law_id=r["법령"], truncated=True)   # 제목만=잘린 근거(truncated) → positive 단정엔 전문 필요
            eff.append(RegEffect(reg_name=r["규제"], law_name=r["법령"], article=r["조"], effect=r["제목"], status="근거확보").model_dump())
        else:   # 미해결(확인필요)도 보존 — 최종 카드서 사라지지 않게 정직 노출(fail-closed)
            eff.append(RegEffect(reg_name=r["규제"], effect=r.get("근거", ""), status="확인필요").model_dump())
    n_ok = sum(1 for r in out if r["상태"] == "근거확보")
    return Command(update={"reg_effects": eff, "evidence_records": ev, "_toolcalls": ["reg_effect_resolve_tool"],
                           "messages": [_tm(f"규제효과 {n_ok}건 근거확보·{len(out) - n_ok}건 확인필요(/{len(out)}) — 근거확보는 조문제목만(truncated); 전문·영향판정은 law_article_fetch 후 record_reg_resolution", tool_call_id)]})


@tool
def procedure_framework_tool(tool_call_id: Annotated[str, InjectedToolCallId] = None) -> Command:
    """표준 건축행정절차 프레임 반환 — '검토할 단계 목록 + 각 단계 근거 법조 포인터'.
    record_procedure_steps의 공급원(reg_effect_resolve_tool이 record_reg_resolution 공급원인 것과 동형).
    코드는 단계 적용여부·순서·허가/신고 택일·면제를 결정하지 않는다(전부 네가 fetch 원문으로 판정).
    사용법: 이 목록의 각 단계마다 ①articles를 law_article_fetch로 읽어 근거확보(근거ID 획득) →
    ②이 케이스 applies(yes/no/unknown)를 네가 판정 → ③의제(record_uijae)는 '건축허가' 단계에 when_note로
    결합 → ④record_procedure_steps(steps=[...])로 커밋. 해당없는 단계도 applies=no(근거와 함께)로
    빠짐없이 넣어라(누락 금지). 단 같은 시점 택일 슬롯(건축허가/건축신고/용도변경/대수선)은 work_type에 맞는 하나만 — 나머지 택일지는 applies=no로도 넣지 말고 드롭('빠짐없이'는 순차 단계에만)."""
    fr = PROC.frame()
    lines = [f"{f['order']:>2}. {f['step_id']}({f['stage_key']}) — 근거: {f['law']} "
             f"제{'·'.join(f['articles'])}조 | 조건: {f['gate_hint']} | 서류단계:{f['is_doc_stage']}"
             for f in fr]
    msg = ("표준 건축행정절차 프레임(검토 대상 단계 + 근거 법조 — 적용여부·순서·면제는 네가 원문으로 판정):\n"
           + "\n".join(lines)
           + "\n\n각 단계: law_article_fetch로 근거확보 → applies 판정 → 해당없어도 applies=no(근거 동반)로 포함"
             " → record_procedure_steps 커밋. '건축허가'엔 record_uijae 의제를 when_note로 결합."
             " (허가/신고/용도변경은 work_type따라 택일)")
    return Command(update={"procedure_frame": fr, "_toolcalls": ["procedure_framework_tool"],
                           "messages": [_tm(msg, tool_call_id)]})


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
            description="이 중첩규제 해소 판정. 해소=법령 근거로 영향없음/충족. 미해소=영향 있어 추가 절차·제한. 해당없음=이 사업과 무관. 확인필요=판단 근거 부족(반드시 unresolved_by 동반).")],
        blocking_level: Annotated[Literal["critical", "normal", "reference"], Field(
            description="차단도. critical=미해소면 진행 자체 불확실한 핵심 입지제한. normal=일반 절차. reference=참고용.")],
        effect: str,
        basis_claims: Annotated[list, Field(
            description="근거계약 [{field_path,claim_type(factual_input/legal_applicability/calculation_basis/authority_discretion),evidence_id,support_role,quote_or_span}]. 결론성(해소/미해소/해당없음)·critical은 필수 — evidence_id가 state에 실재해야(law_article_fetch 등으로 먼저 근거 확보).")] = None,
        unresolved_by: Annotated[Literal["none", "agent", "user", "authority", "data_unavailable"], Field(
            description="status=확인필요면 누가 푸나(필수). agent=더 조사하면 풀림(최종 완료 금지·다시 조사). user=사용자만 아는 사실. authority=관할 심의/재량(그게 재량임을 말하는 법령근거 basis_claims 필수). data_unavailable=데이터원 부재.")] = "none",
        basis_seq: list = None,
        state: Annotated[dict, InjectedState] = None,
        tool_call_id: Annotated[str, InjectedToolCallId] = None) -> Command:
    """중첩규제(reg_overlaps) 1건의 영향판정을 커밋 — reg_effect_resolve_tool/law_article_fetch로 법령을 fetch한 뒤 그 근거로 '이 사업에 어떤 영향인지'를 네가 판정해 기록(코드는 근거 실재만 검증, 의미판단은 너).
    근거계약: 결론성(해소/미해소/해당없음)·critical은 basis_claims 필수+실재. 확인필요는 unresolved_by 분류 필수(bare 확인필요 금지)."""
    state = state or {}
    claims = [c for c in (basis_claims or []) if isinstance(c, dict)]
    seq = [s for s in (basis_seq or []) if isinstance(s, int)]
    ub = unresolved_by if unresolved_by in _UNRESOLVED_VALUES else "none"
    _need_basis = status in ("해소", "미해소", "해당없음") or blocking_level == "critical"
    if _need_basis:
        ok, errs = validate_basis_claims(state, claims)
        if not claims or not ok:
            why = "근거(basis_claims) 없음" if not claims else f"근거 미실재{errs[:3]}"
            return Command(update={"_reject_count": 1, "messages": [_tm(
                f"<tool_use_error>'{reg_name}' {status}/{blocking_level} 단정은 근거계약(basis_claims) 필수·실재({why}). evidence_id를 state 실재 근거로 달거나 status='확인필요'+unresolved_by로 커밋하라.</tool_use_error>", tool_call_id)]})
    if status == "확인필요":
        if ub == "none":
            return Command(update={"_reject_count": 1, "messages": [_tm(
                f"<tool_use_error>'{reg_name}' 확인필요는 unresolved_by 분류 필수 — bare 확인필요 금지. 더 조사 가능=agent, 관할재량=authority(법령근거 동반), 사용자사실=user, 데이터부재=data_unavailable.</tool_use_error>", tool_call_id)]})
        if ub == "authority":   # authority punt 방지(0a): 관할재량임을 말하는 법령근거 필수
            ok, _ = validate_basis_claims(state, claims)
            if not (claims and ok and any(c.get("claim_type") == "authority_discretion" for c in claims)):
                return Command(update={"_reject_count": 1, "messages": [_tm(
                    f"<tool_use_error>'{reg_name}' unresolved_by=authority는 '관할 심의/재량'임을 말하는 법령근거(claim_type=authority_discretion·evidence_id 실재) 필수. 근거 없으면 agent로 더 조사하라.</tool_use_error>", tool_call_id)]})
    eff = RegEffect(reg_name=reg_name, effect=str(effect)[:200], status=status, resolution_committed=True,
                    blocking_level=blocking_level, unresolved_by=ub, basis_seq=seq, basis_claims=claims).model_dump()
    return Command(update={"reg_effects": [eff], "_toolcalls": ["record_reg_resolution"], "_reject_count": 0,
                           "messages": [_tm(f"규제해소 기록: {reg_name} → {status}({blocking_level}{'/'+ub if ub != 'none' else ''})", tool_call_id)]})


@tool
def record_use_classification(
        original_use: str, canonical_use: str, law_basis: str,
        basis_claims: Annotated[list, Field(description="별표1 근거계약 [{field_path,claim_type,evidence_id,support_role,quote_or_span}]. status=확정은 필수·실재(law_byeolpyo_fetch로 별표1 먼저 확보).")] = None,
        status: Annotated[Literal["확정", "확인필요"], Field(description="확정=별표1 근거로 canonical 세목 확정. 확인필요=모호(unresolved_by 동반).")] = "확인필요",
        unresolved_by: Annotated[Literal["none", "agent", "user", "authority", "data_unavailable"], Field(description="확인필요면 누가 푸나(필수).")] = "none",
        state: Annotated[dict, InjectedState] = None,
        tool_call_id: Annotated[str, InjectedToolCallId] = None) -> Command:
    """생활어(카페/피시방/사무소)를 건축법 시행령 별표1 canonical 세목(휴게음식점/인터넷컴퓨터게임시설제공업소/업무시설 등)으로 확정 커밋 — act_landuse 선결.
    코드는 생활어→세목 매핑을 안 한다(네가 별표1 fetch해 확정). status=확정은 별표1 근거(basis_claims) 필수·실재."""
    state = state or {}
    claims = [c for c in (basis_claims or []) if isinstance(c, dict)]
    ub = unresolved_by if unresolved_by in _UNRESOLVED_VALUES else "none"
    if status == "확정":
        ok, errs = validate_basis_claims(state, claims)
        if not claims or not ok:
            return Command(update={"_reject_count": 1, "messages": [_tm(
                f"<tool_use_error>용도분류 '확정'은 건축법 시행령 별표1 근거(basis_claims) 필수·실재({'근거없음' if not claims else errs[:2]}). law_byeolpyo_fetch로 별표1 확보 후 그 evidence로 커밋하거나 status='확인필요'+unresolved_by로.</tool_use_error>", tool_call_id)]})
    if status == "확인필요" and ub == "none":
        return Command(update={"_reject_count": 1, "messages": [_tm(
            "<tool_use_error>용도분류 '확인필요'는 unresolved_by(agent/user/...) 분류 필수 — bare 확인필요 금지.</tool_use_error>", tool_call_id)]})
    uc = UseClassification(original_use=str(original_use)[:60], canonical_use=str(canonical_use)[:60],
                           law_basis=str(law_basis)[:120], basis_claims=claims, status=status, unresolved_by=ub).model_dump()
    return Command(update={"use_classifications": [uc], "_toolcalls": ["record_use_classification"], "_reject_count": 0,
                           "messages": [_tm(f"용도분류 기록: {original_use} → {canonical_use} ({status}{'/'+ub if ub != 'none' else ''})", tool_call_id)]})


@tool
def record_work_type(
        work_type: Annotated[Literal["신축", "용도변경", "대수선", "증축", "해체", "확인필요"], Field(description="공사 종류. get_building_register(기존건물 유무)·사용자 답변을 종합해 판단(빈땅→신축, 기존건물 용도만 변경→용도변경 등).")],
        basis_claims: Annotated[list, Field(description="근거계약 [{field_path,claim_type,evidence_id,...}]. status=확정은 필수·실재(건축물대장 api evidence는 claim_type=factual_input, 사용자답변은 user_fact). 접도(맹지)·절차 게이트가 이 커밋값만 읽는다.")] = None,
        status: Annotated[Literal["확정", "확인필요"], Field(description="확정=근거로 work_type 확정. 확인필요=모호(unresolved_by 동반).")] = "확인필요",
        unresolved_by: Annotated[Literal["none", "agent", "user", "authority", "data_unavailable"], Field(description="확인필요면 누가 푸나(보통 user=빈땅/기존건물 사실).")] = "none",
        state: Annotated[dict, InjectedState] = None,
        tool_call_id: Annotated[str, InjectedToolCallId] = None) -> Command:
    """공사 종류(신축/용도변경/대수선/증축/해체)를 구조화 커밋 — 접도(맹지)·절차 게이트가 읽는 단일원(코드는 raw work_type/document_facts 문자열 추론 안 함).
    status=확정은 근거(basis_claims) 필수·실재(건축물대장·사용자 답변). 확인필요는 unresolved_by 분류."""
    state = state or {}
    claims = [c for c in (basis_claims or []) if isinstance(c, dict)]
    ub = unresolved_by if unresolved_by in _UNRESOLVED_VALUES else "none"
    wt = work_type if work_type in ("신축", "용도변경", "대수선", "증축", "해체", "확인필요") else "확인필요"
    if status == "확정":
        ok, errs = validate_basis_claims(state, claims)
        if not claims or not ok:
            return Command(update={"_reject_count": 1, "messages": [_tm(
                f"<tool_use_error>work_type '확정'은 근거(basis_claims) 필수·실재({'근거없음' if not claims else errs[:2]}). 건축물대장(get_building_register) 또는 사용자 답변(user_fact) 근거로 커밋하거나 status='확인필요'+unresolved_by로.</tool_use_error>", tool_call_id)]})
    if status == "확인필요" and ub == "none":
        ub = "user"   # work_type은 보통 사용자만 아는 사실(빈땅/기존건물)
    wtr = WorkTypeResolution(work_type=wt, status=status if status in ("확정", "확인필요") else "확인필요",
                             unresolved_by=ub, basis_claims=claims).model_dump()
    return Command(update={"work_type_resolutions": [wtr], "_toolcalls": ["record_work_type"], "_reject_count": 0,
                           "messages": [_tm(f"공사종류 기록: {wt} ({status}{'/'+ub if ub != 'none' else ''})", tool_call_id)]})


@tool
def record_landuse_resolution(
        intended_use: str, matched_node_desc: str, api_reg_nm: str,
        status: Annotated[Literal["가능", "불가", "조건필요", "확인필요"], Field(description="행위제한 판정. 가능=별표1/조례 근거로 허용. 불가=금지. 조건필요=조건부. 확인필요=세목불일치·근거불충분(unresolved_by 동반).")],
        basis_claims: Annotated[list, Field(description="근거계약. 가능/불가/조건필요는 필수·실재. matched_node_desc가 intended_use와 다르면 가능 금지(세목 불일치).")] = None,
        unresolved_by: Annotated[Literal["none", "agent", "user", "authority", "data_unavailable"], Field(description="확인필요면 누가 푸나(필수).")] = "none",
        mismatch_reason: str = "",
        state: Annotated[dict, InjectedState] = None,
        tool_call_id: Annotated[str, InjectedToolCallId] = None) -> Command:
    """행위제한 raw(act_landuse) 위에 **NODE_DESC↔intended_use 일치를 네가 확인**하고 가부를 커밋 — 코드 act_verdict 승격 대체(조례판정 record_ordinance_ruling과 별개).
    가능/불가/조건필요 단정은 근거(basis_claims) 필수·실재. matched_node_desc가 의도 세목과 다르면 가능 금지(mismatch_reason 적고 확인필요/조례확인)."""
    state = state or {}
    claims = [c for c in (basis_claims or []) if isinstance(c, dict)]
    ub = unresolved_by if unresolved_by in _UNRESOLVED_VALUES else "none"
    if status in ("가능", "불가", "조건필요"):
        ok, errs = validate_basis_claims(state, claims)
        if not claims or not ok:
            return Command(update={"_reject_count": 1, "messages": [_tm(
                f"<tool_use_error>행위제한 '{status}' 단정은 근거(basis_claims) 필수·실재({'근거없음' if not claims else errs[:2]}). 별표1/조례 근거를 달거나 status='확인필요'+unresolved_by로.</tool_use_error>", tool_call_id)]})
    if status == "확인필요":
        if ub == "none":
            return Command(update={"_reject_count": 1, "messages": [_tm(
                "<tool_use_error>행위제한 '확인필요'는 unresolved_by 분류 필수 — bare 확인필요 금지.</tool_use_error>", tool_call_id)]})
        if ub == "authority":   # authority punt 방지(0a) — 관할 재량임을 말하는 법령근거 필수(record_reg_resolution과 일관)
            ok, _ = validate_basis_claims(state, claims)
            if not (claims and ok and any(c.get("claim_type") == "authority_discretion" for c in claims)):
                return Command(update={"_reject_count": 1, "messages": [_tm(
                    "<tool_use_error>행위제한 unresolved_by=authority는 '관할 심의/재량'임을 말하는 법령근거(claim_type=authority_discretion·evidence_id 실재) 필수. 근거 없으면 agent로 더 조사하라.</tool_use_error>", tool_call_id)]})
    lr = LanduseResolution(intended_use=str(intended_use)[:60], matched_node_desc=str(matched_node_desc)[:120],
                           api_reg_nm=str(api_reg_nm)[:40], status=status, unresolved_by=ub,
                           basis_claims=claims, mismatch_reason=str(mismatch_reason)[:200]).model_dump()
    return Command(update={"landuse_resolutions": [lr], "_toolcalls": ["record_landuse_resolution"], "_reject_count": 0,
                           "messages": [_tm(f"행위제한 판정: {intended_use} → {status}{'/'+ub if ub != 'none' else ''}", tool_call_id)]})


@tool
def record_procedure_steps(
        steps: Annotated[list, Field(description="인허가 절차 타임라인 [{step_id, order, stage_key, applies(yes/no/unknown), status(근거확보/확인필요), unresolved_by, actor, authority, trigger, action, when_note, deadline, law_name, article, basis_claims, requires_documents, related_document_stage_keys, source_api, notes}]. documents와 별개(절차 순서·주체·관할). verdict/가부 안 만듦.")],
        state: Annotated[dict, InjectedState] = None,
        tool_call_id: Annotated[str, InjectedToolCallId] = None) -> Command:
    """인허가 행정 절차 타임라인을 커밋(건축허가/건축신고/용도변경/가설건축물/해체/착공신고/감리/사용승인/건축물대장/유지관리 등 — 네가 법령 근거로 분기·구성).
    documents(제출서류)와 분리. 비신축은 신축3단계(건축허가/착공/사용승인) 상속 금지. 근거계약(field 단위 basis_claims): status=근거확보·applies=no(비해당) 확정은 근거 필수·실재 → 없으면 확인필요로 강등. 확인필요는 unresolved_by 분류."""
    state = state or {}
    out = []
    for s in (steps or []):
        if not isinstance(s, dict) or not s.get("step_id"):
            continue
        claims = [c for c in (s.get("basis_claims") or []) if isinstance(c, dict)]
        applies = s.get("applies", "yes"); applies = applies if applies in ("yes", "no", "unknown") else "yes"
        status = s.get("status", "확인필요"); status = status if status in ("근거확보", "확인필요") else "확인필요"
        ub = s.get("unresolved_by", "none"); ub = ub if ub in _UNRESOLVED_VALUES else "none"
        if status == "근거확보" or applies == "no":   # 근거 없는 확정/비해당 금지 → 강등(확정 세탁 방지)
            ok, _ = validate_basis_claims(state, claims)
            if not (claims and ok):
                status = "확인필요"
                if applies == "no":
                    applies = "unknown"
                if ub == "none":
                    ub = "agent"
        if status == "확인필요" and ub == "none":
            ub = "agent"   # bare 확인필요 방지(기본 agent=더 조사)
        out.append(ProcedureStep(
            step_id=str(s.get("step_id"))[:40], order=float(s.get("order") or 0), stage_key=str(s.get("stage_key", ""))[:40],
            applies=applies, status=status, unresolved_by=ub, actor=str(s.get("actor", ""))[:60], authority=str(s.get("authority", ""))[:60],
            trigger=str(s.get("trigger", ""))[:120], action=str(s.get("action", ""))[:200], when_note=str(s.get("when_note", ""))[:200],
            deadline=str(s.get("deadline", ""))[:60], law_name=str(s.get("law_name", ""))[:60], article=str(s.get("article", ""))[:40],
            title_from_law=str(s.get("title_from_law", ""))[:120], quote=str(s.get("quote", ""))[:200], basis_claims=claims,
            citation_ids=[str(x) for x in _aslist(s.get("citation_ids"))], related_document_stage_keys=[str(x) for x in _aslist(s.get("related_document_stage_keys"))],
            requires_documents=bool(s.get("requires_documents")), source_api=str(s.get("source_api", ""))[:40],
            notes=[str(x)[:120] for x in _aslist(s.get("notes"))]).model_dump())
    if not out:
        return Command(update={"messages": [_tm("<tool_use_error>record_procedure_steps: step_id 있는 절차 1개 이상 필요.</tool_use_error>", tool_call_id)]})
    return Command(update={"procedure_steps": out, "_toolcalls": ["record_procedure_steps"], "_reject_count": 0,
                           "messages": [_tm(f"절차 {len(out)}건 기록", tool_call_id)]})


@tool
def record_ordinance_ruling(
        verdict: Annotated[Literal["가능", "불가", "확인필요"], Field(
            description="조례 별표 호목해소 결론. 가능=제공된 별표 원문 호목이 해당 용도를 명시적으로 허용. "
                        "불가=원문이 명시적으로 금지. 확인필요=별표 본문 미확보·호목 참조 미해소·근거 불충분 등 판단 불가(기본값, 기권).")],
        hojeok_path: str, cited_count: int, relied_source_ids: list,
        state: Annotated[dict, InjectedState] = None,
        tool_call_id: Annotated[str, InjectedToolCallId] = None) -> Command:
    """agent 멀티홉 호목해소 결론 커밋. verdict는 위 3개 enum 중 하나만(자유서술 금지).
    relied_source_ids = 이 판정이 의존한 근거ID들(ToolMessage 머리의 '근거ID:...'를 그대로 — state에 실재해야, 허위 거부). 그 근거 별표가 잘렸으면(truncated) '가능/불가'가 자동 강등(확인필요)된다.
    환각가드: '가능/불가' 단정은 인용근거(cited_count≥1)+relied_source_ids 실재 필수 + build_reasoning(basis·truncated_basis)·route(citations==0→abstain) 다층."""
    state = state or {}
    _sids = [str(s) for s in (relied_source_ids or []) if s]
    if verdict in ("가능", "불가"):
        if cited_count < 1:   # 근거 없는 단정 거부 — 재호출 유도(_toolcalls 안 남겨 retry 열어둠)
            return Command(update={"_reject_count": 1, "messages": [_tm(
                f"<tool_use_error>'{verdict}' 단정은 인용 근거가 필요(cited_count≥1). 별표 원문 호목을 인용해 다시 커밋하거나, 근거 없으면 verdict='확인필요'로 커밋하라.</tool_use_error>", tool_call_id)]})
        _unreal = [s for s in _sids if s not in collect_evidence_ids(state)]   # §6a: relied도 state 실재 evidence여야(허위 근거ID 차단)
        if not _sids or _unreal:
            return Command(update={"_reject_count": 1, "messages": [_tm(
                f"<tool_use_error>'{verdict}' 단정의 relied_source_ids가 비었거나 미실재({_unreal[:3]}). 별표/법령을 fetch한 근거ID(ToolMessage '근거ID:...')만 달아라(지어내면 거부).</tool_use_error>", tool_call_id)]})
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
        dimensions: list, basis_seq: list = None, basis_claims: Annotated[list, Field(
            description="종합판정 근거계약 [{field_path,claim_type,evidence_id,support_role,quote_or_span}]. 각 dimension도 자체 basis_claims를 가질 수 있다. evidence_id는 state에 실재해야(허위 거부). user 사실은 claim_type=factual_input만.")] = None,
        state: Annotated[dict, InjectedState] = None,
        tool_call_id: Annotated[str, InjectedToolCallId] = None) -> Command:
    """진단 최종판정을 LLM(너)이 합성해 커밋(코드 if/else 판정 대체). 이게 진단의 결론이다.
    dimensions = 이 케이스에서 실제로 가부를 가른 '판정 축'들을 **네가 정해** 나열(고정 목록 아님):
      [{dimension: 축 이름, status: '충족'|'주의'|'확인필요'|'불가', reason: 한 줄, basis_seq: 표시용 seq, basis_claims: [근거계약],
        blocking_level: 'critical'|'none', unresolved_by: 'authority'(관할심의·법령근거 동반)|'agent'(더 조사)|'user'|'data_unavailable'|'none'}].
    근거계약: 모든 basis_claims의 evidence_id는 state 실재 근거여야(허위 거부). final_verdict '가능'/'가능(조건부)'면 basis_seq 필수 + 차단 축(불가·critical·미해소 agent/authority) 위엔 불가."""
    state = state or {}
    dims = [d for d in (dimensions or []) if isinstance(d, dict)]
    # 0a: unknown unresolved_by 조용히 none 강등 금지 — 비-enum이면 거부
    _bad_ub = sorted({str(d.get("unresolved_by", "none")) for d in dims if str(d.get("unresolved_by", "none")) not in _UNRESOLVED_VALUES})
    if _bad_ub:
        return Command(update={"_reject_count": 1, "messages": [_tm(
            f"<tool_use_error>unresolved_by 비정상값 {_bad_ub} — {list(_UNRESOLVED_VALUES)} 중 하나로 명시하라(코드가 조용히 none으로 안 바꿈).</tool_use_error>", tool_call_id)]})
    # item 11: 근거계약 검증 — 전 basis_claims(top + per-dim) evidence_id 실재 + quote 실재(허위 ID-washing 거부)
    all_claims = [c for c in (basis_claims or []) if isinstance(c, dict)]
    for d in dims:
        all_claims += [c for c in (d.get("basis_claims") or []) if isinstance(c, dict)]
    if all_claims:
        ok, errs = validate_basis_claims(state, all_claims)
        if not ok:
            return Command(update={"_reject_count": 1, "messages": [_tm(
                f"<tool_use_error>종합판정 근거계약 위반(허위/미실재 evidence): {errs[:3]}. basis_claims의 evidence_id는 fetch한 state 실재 근거여야 한다.</tool_use_error>", tool_call_id)]})
    # 차단 축(완료계약 U3): 불가 OR critical OR 미해소(agent/authority). 위에 '가능'계열 못 얹음. soft(확인필요)는 '가능'만 추가 차단.
    blocked = [d for d in dims if str(d.get("status", "")) == "불가"
               or str(d.get("blocking_level", "")) == "critical"
               or str(d.get("unresolved_by", "none")) in ("agent", "authority")]
    soft = [d for d in dims if str(d.get("status", "")) == "확인필요"]
    bad = blocked + soft if final_verdict == "가능" else blocked
    if final_verdict in ("가능", "가능(조건부)") and (not basis_seq or bad):
        why = "인용 근거(basis_seq)가 없다" if not basis_seq else f"미충족 축({[(d.get('dimension'), d.get('status'), d.get('unresolved_by', 'none')) for d in bad]})이 있는데 종합이 '{final_verdict}'다 — 불가·critical·미해소(agent/authority) 축 위엔 '가능'계열 불가, '확인필요' 축 위엔 무조건'가능' 불가"
        return Command(update={"_reject_count": 1, "messages": [_tm(
            f"<tool_use_error>종합판정 거부: {why}. 근거를 달거나, 막힌 축이 있으면 final_verdict를 '확인필요'/'위험·금지'로 다시 커밋하라.</tool_use_error>", tool_call_id)]})
    def _mk(d):
        st = str(d.get("status", "주의"))
        if st not in ("충족", "주의", "확인필요", "불가"):
            st = "주의"
        bl = str(d.get("blocking_level", "none"))
        if bl not in ("none", "critical"):
            bl = "none"
        ub = str(d.get("unresolved_by", "none"))   # 위서 비-enum은 이미 거부됨(조용한 강등 없음)
        return VerdictLabel(dimension=str(d.get("dimension", ""))[:40], status=st,
                            reason=str(d.get("reason", ""))[:200],
                            basis_seq=[s for s in (d.get("basis_seq") or []) if isinstance(s, int)],
                            blocking_level=bl, unresolved_by=ub,
                            basis_claims=[c for c in (d.get("basis_claims") or []) if isinstance(c, dict)]).model_dump()
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
    _beid = _ev_id("api", "building_register", pnu)   # item 0b: 건축물대장 EvidenceRecord(work_type 근거로 인용 가능)
    return Command(update={"document_facts": {"기존건물": fact},
                           "evidence_records": {_beid: _ev_record(_beid, "api", msg, source_url="건축HUB getBrTitleInfo")},
                           "_toolcalls": ["get_building_register"],
                           "messages": [_tm(msg + f" (근거ID:{_beid})", tool_call_id)]})


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
         author_rule_tool, reg_effect_resolve_tool, procedure_framework_tool, record_uijae, record_reg_resolution, record_ordinance_ruling, record_verdict,
         record_use_classification, record_landuse_resolution, record_procedure_steps, record_work_type,
         request_human_input]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}
