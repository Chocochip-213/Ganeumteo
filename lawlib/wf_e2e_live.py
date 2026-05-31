#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""진짜 무하드코딩 e2e — 입력(입지·조례판정)까지 전부 라이브.
입지=VWorld 라이브 / 행위제한=data.go.kr 라이브 / 조례 가부·건폐율=ordin+HWP 라이브 추출(내가 RAG) /
서류=wf_docs_agent 조문전수 / 규제효과=wf_reg_agent 법령조회 / 작성주체=건축법§23 라이브.
하드코딩=라우팅 시드만(지목→전용법, 용도지역→조례별표 제목매칭). 결과=파일 저장.
사용: python wf_e2e_live.py "<주소>" <road|parcel> [면적] [용도]"""
import urllib.request, urllib.parse, json, time, re, sys, io, zlib
import wf_docs_agent as DOC, wf_reg_agent as REG, wf_roadmap as RM
import law_fetch as L
try: import olefile
except: olefile=None

VW="1E6285EC-6D3A-367C-AE65-CBD3510DEE9C"; DK="a76ca13a01f4a886710c3ff53bb0e6746d8fff0bb27c5e6b8f4c87292a6bad4e"; DOM="http://localhost"
def get(url,p,tries=5,euckr=False):
    qs=urllib.parse.urlencode(p,safe=':()')
    for i in range(tries):
        try:
            raw=urllib.request.urlopen(urllib.request.Request(f"{url}?{qs}",headers={"User-Agent":"Mozilla/5.0","Connection":"close"}),timeout=40).read()
            return raw.decode("euc-kr","replace") if euckr else raw.decode("utf-8","replace")
        except Exception: time.sleep(1.2*(i+1))
    return ""
def geo(a,t):
    r=get("https://api.vworld.kr/req/address",{"service":"address","request":"getcoord","version":"2.0","crs":"epsg:4326","address":a,"type":t,"format":"json","key":VW})
    try:
        j=json.loads(r)
        if j["response"]["status"]=="OK": p=j["response"]["result"]["point"]; return float(p["x"]),float(p["y"])
    except: return None
def parcel(x,y):
    r=get("https://api.vworld.kr/req/data",{"service":"data","request":"GetFeature","version":"2.0","data":"LP_PA_CBND_BUBUN","format":"json","crs":"EPSG:4326","geometry":"false","size":1,"geomFilter":f"POINT({x} {y})","key":VW,"domain":DOM})
    try: return json.loads(r)["response"]["result"]["featureCollection"]["features"][0]["properties"]
    except: return {}
def ned(ep,pnu,ex=None):
    p={"key":VW,"pnu":pnu,"format":"json","numOfRows":15,"pageNo":1,"domain":DOM}
    if ex:p.update(ex)
    try: return json.loads(get(f"http://api.vworld.kr/ned/data/{ep}",p))
    except: return {}
def dig(j,k): return re.findall(rf'"{k}"\s*:\s*"([^"]*)"',json.dumps(j,ensure_ascii=False))
def act(uc,nm,ac):
    r=get("http://apis.data.go.kr/1613000/arLandUseInfoService/DTarLandUseInfo",{"serviceKey":DK,"areaCd":ac,"ucodeList":uc,"landUseNm":nm,"numOfRows":5,"pageNo":1},euckr=True)
    return re.findall(r"<REG_NM>(.*?)</REG_NM>",r)

def act_detail(uc,nm,ac):
    """행위제한 응답을 item별로 파싱 — REG_NM(가부신호)+LU_REF_LAW_NM1(근거조항)+NODE_DESC(시설명) 동반 반환.
    act()가 버리던 근거조항을 보존해 LLM이 인용·판정 근거로 쓰게 함(grounding 복구)."""
    r=get("http://apis.data.go.kr/1613000/arLandUseInfoService/DTarLandUseInfo",{"serviceKey":DK,"areaCd":ac,"ucodeList":uc,"landUseNm":nm,"numOfRows":5,"pageNo":1},euckr=True)
    out=[]
    for it in re.findall(r"<item>(.*?)</item>",r,re.S):
        g=lambda k:(re.findall(rf"<{k}>(.*?)</{k}>",it,re.S) or [""])[0].strip()
        reg=g("REG_NM")
        if reg: out.append({"reg":reg,"ref_law":g("LU_REF_LAW_NM1"),"node":g("NODE_DESC")})
    return out

def building_register(pnu):
    """건축물대장 표제부(건축HUB getBrTitleInfo) — 필지에 '기존 건물'이 있나(=신축 vs 용도변경 자동판별). PNU에서 시군구/법정동/본번/부번 분해.
    반환: 건물있음=True(주용도·연면적·층수·동수) / False(빈땅 가능) / None(조회불가 — 건축HUB 활용신청 필요). 빈 응답을 '빈땅 확정'으로 단정하지 않음."""
    s=str(pnu or "")
    if len(s)<19: return {"건물있음":None,"사유":"PNU 없음"}
    plat="1" if s[10]=="2" else "0"   # PNU 필지구분 2=산→platGbCd 1, else 0(대지)
    r=get("http://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo",
          {"serviceKey":DK,"sigunguCd":s[:5],"bjdongCd":s[5:10],"platGbCd":plat,"bun":s[11:15],"ji":s[15:19],"numOfRows":50,"pageNo":1})
    if not r:   # 200/0바이트 = 건축HUB 미활용신청 → 조회불가(빈땅 단정 금지)
        return {"건물있음":None,"사유":"건축물대장 조회불가(건축HUB API 활용신청 필요 — data.go.kr/15134735)"}
    code=(re.findall(r"<resultCode>(.*?)</resultCode>",r) or [""])[0]
    items=re.findall(r"<item>(.*?)</item>",r,re.S)
    if not items:
        return {"건물있음":False,"사유":f"등록된 건축물 없음(빈땅 가능) code={code}"}
    g=lambda k:(re.findall(rf"<{k}>(.*?)</{k}>",r) or [""])[0].strip()
    return {"건물있음":True,"동수":len(items),"주용도":g("mainPurpsCdNm"),"연면적":g("totArea"),"지상층수":g("grndFlrCnt"),"건물명":g("bldNm")}

def _S(v):
    if v is None:return ''
    if isinstance(v,list):return ' '.join(_S(x) for x in v)
    if isinstance(v,dict):return _S(v.get('조내용') or v.get('항내용') or v.get('호내용') or '')
    return str(v)
def _dl(u,t=4):
    for i in range(t):
        try: return urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0","Connection":"close"}),timeout=40).read()
        except: time.sleep(1.5)
    return None

def jorye_rag(sigungu, zone, 용도키워드=("일반음식점","휴게음식점","제2종근린생활","2종근린생활")):
    """라이브 조례 RAG: 시군구 도시계획조례 → 용도지역 건축가능 별표 제목매칭 → HWP 추출 → 카페 가부 + 건폐율/용적률."""
    out={"상태":"기권","시군구":sigungu,"용도지역":zone}
    try:
        s=L.ordin_search(f"{sigungu} 도시계획")  # '도시계획'/'군계획' 둘다 매칭, 도명 빼고 시군구만
        items=s.get("items") or []
        # 정확매칭: '계획' 포함(도시계획/군계획) + 시군구명 포함
        cand=[it for it in items if "계획" in _S(it.get("자치법규명")) and sigungu in _S(it.get("자치법규명"))]
        if not cand: cand=items
        if not cand: out["사유"]="조례 검색 0건"; return out
        mst=cand[0].get("자치법규일련번호") or cand[0].get("MST")
        out["조례"]=_S(cand[0].get("자치법규명")); out["MST"]=mst
        j=L.ordin_service(mst)
        # 1) 건폐율·용적률 = 조문 inline (조 노드 keyword 검색)
        for u in (j.get("조문",{}).get("조") or []):
            if not isinstance(u,dict): continue
            c=_S(u.get("조내용"))
            if "건폐율" in c and zone in c:
                m=re.search(rf'{zone}[^0-9]*([0-9]+)\s*퍼센트',c)
                if m: out["건폐율"]=m.group(1)+"%"
            if "용적률" in c and zone in c:
                m=re.search(rf'{zone}[^0-9]*([0-9]+)\s*퍼센트',c)
                if m: out["용적률"]=m.group(1)+"%"
        # 2) 용도지역 건축가능/불가 별표 = 제목매칭(번호 비의존). 포지티브('있는')/네거티브('없는') 자동판별
        bu=j.get("별표",{}).get("별표단위") or []
        if isinstance(bu,dict): bu=[bu]
        tgt=None; mode=None
        for b in bu:
            ti=_S(b.get("별표제목"))
            if isinstance(b,dict) and zone in ti and "건축할 수 있는" in ti: tgt,mode=b,"pos"; break
        if not tgt:
            for b in bu:
                ti=_S(b.get("별표제목"))
                if isinstance(b,dict) and zone in ti and "건축할 수 없는" in ti: tgt,mode=b,"neg"; break
        if not tgt: out["사유"]=f"'{zone} 건축할 수 있는/없는' 별표 없음"; return out
        out["별표"]=_S(tgt.get("별표번호"))+" "+_S(tgt.get("별표제목"))[:30]+f" [{mode}]"
        url=_S(tgt.get("별표첨부파일명"))
        raw=_dl(url) if url else None
        if not raw: out["사유"]="별표 HWP 다운 실패"; return out
        if raw[:4]!=bytes.fromhex("d0cf11e0"):
            out["상태"]="확인필요"; out["사유"]=f"HWP아님(magic {raw[:4].hex()}=hwpx/이미지)→형식핸들 필요"; return out
        if not olefile: out["사유"]="olefile 없음"; return out
        # ★ BodyText 완전텍스트 우선(PrvText 1000자 캡 회피), 실패시 PrvText fallback
        o=olefile.OleFileIO(io.BytesIO(raw)); full=""; src=""
        try: full=zlib.decompress(o.openstream("BodyText/Section0").read(),-15).decode("utf-16-le","ignore"); src="BodyText(완전)"
        except Exception:
            try: full=o.openstream("PrvText").read().decode("utf-16-le","ignore"); src="PrvText(캡)"
            except Exception: pass
        o.close()
        if not full: out["사유"]="텍스트 추출 실패"; return out
        clean=re.sub(r'\s+',' ',re.sub(r'[^가-힣0-9().,ㆍ· ]',' ',full))
        out["원문길이"]=len(full); out["추출"]=src
        포함=[k for k in 용도키워드 if k in clean]
        # 별표 의미(포지티브=허용목록/네거티브=금지목록)에 따라만 해석 — 실존 2종, 과적합 아님. 판정=완전텍스트 기준
        out["상태"]=("가능" if 포함 else "불가") if mode=="pos" else ("불가" if 포함 else "가능")
        out["근거"]=f"[{mode}]{src} 완전텍스트 음식점/근생={포함 or '없음'}"
        for k in (포함 or 용도키워드):  # 근거 인용(실제 호목)
            m=re.search(rf'.{{0,45}}{k}.{{0,8}}',clean)
            if m: out["인용"]=m.group(0).strip()[:110]; break
        return out
    except Exception as e:
        out["사유"]=f"예외:{e}"; return out

JIMOK_UIJAE={"전":"농지전용","답":"농지전용","과수원":"농지전용","임야":"산지전용"}

def run(addr,atype,area=264,용도="카페(일반음식점)"):
    log=[]; P=lambda *a: (print(*a), log.append(" ".join(str(x) for x in a)))
    P("="*72); P(f"[무하드코딩 e2e] {addr} | {용도} {area}㎡"); P("="*72)
    xy=geo(addr,atype); time.sleep(.5)
    if not xy: P("지오코딩 실패"); return "\n".join(log)
    pc=parcel(*xy); time.sleep(.5); pnu=pc.get("pnu"); ac=(pnu or "")[:5]
    addr_full=pc.get("addr","") or addr
    _tk=addr_full.split()
    sigungu=([t for t in _tk if t.endswith("시")] or [t for t in _tk if t.endswith("군")] or [t for t in _tk if t.endswith("구")] or [""])[0]
    jimok=(re.findall(r'[가-힣]+',pc.get('jibun','') or '') or [''])[-1]
    jimok={"임":"임야","과":"과수원","목":"목장용지","잡":"잡종지"}.get(jimok,jimok)
    lc=ned("getLandCharacteristics",pnu); time.sleep(.5)
    zone=(dig(lc,"prposArea1Nm") or [None])[0]
    road=(dig(lc,"roadSideCodeNm") or [None])[0]  # 도로접면: 맹지/중로각지/세로(가)/세로(불)... (KLIS)
    lu=ned("getLandUseAttr",pnu); time.sleep(.5)
    uq=re.findall(r'"prposAreaDstrcCode"\s*:\s*"(UQ[A-Z][0-9]+)"',json.dumps(lu,ensure_ascii=False))
    regs=list(dict.fromkeys(dig(lu,"prposAreaDstrcCodeNm")))
    _pp=[(int(_y.group(1)),int(_v.group(1))) for _r in re.findall(r"\{[^{}]*\}",json.dumps(ned("getIndvdLandPriceAttr",pnu),ensure_ascii=False)) for _y in [re.search(r'"stdrYear"\s*:\s*"(\d{4})"',_r)] for _v in [re.search(r'"pblntfPclnd"\s*:\s*"(\d+)"',_r)] if _y and _v and int(_v.group(1))>0]
    price=str(max(_pp)[1]) if _pp else "?"
    P(f"[입지·라이브] {addr_full}")
    P(f"  PNU={pnu} 지목={jimok} 용도지역={zone} 도로접면={road} 공시지가={price}원/㎡")
    P(f"  규제중첩={regs}")
    if road=="맹지": P(f"  ⚠️ 맹지(도로 미접) — 건축법 §44 접도의무: 진입로(사도개설 사도법§4/현황도로 인정) 필요. 건축 함정.")
    allreg=(regs or [])+([zone] if zone else [])
    # 강제금지 1차
    if any('개발제한' in r for r in allreg):
        P("\n[판정] 위험·금지 — 개발제한구역(라이브 규제효과 조회):")
        for g in REG.resolve(["개발제한구역"]):
            if g["상태"]=="근거확보": P(f"  {g['법령']} {g['조']} — {g['인용'][:80]}")
        P("[서류] 없음. 매수전 함정."); return "\n".join(log)
    # 행위제한 라이브 — 시설명=용도 인자에서 추출(괄호 안 건축법 용도명 우선, 없으면 용도 그대로). 하드코딩 제거
    _m=re.search(r'\(([^)]+)\)',용도); 시설명=(_m.group(1) if _m else 용도).strip()
    verdict="확인필요"; basis=""
    if uq:
        rg=act(uq[0],시설명,ac); time.sleep(.4)
        if rg and rg[0]=="가능": verdict,basis="가능(법령직접)",f"{zone} {시설명}=행위제한 API 가능"
        elif rg and rg[0]=="금지": verdict,basis="조례확인필요",f"{zone} API 금지=입지제한/조례위임 → 조례 RAG"
        else: verdict,basis="조례확인필요",f"{zone} 조례위임(API 빈값) → 조례 RAG"
    P(f"\n[1차판정·행위제한] {verdict} — {basis}")
    # 조례 RAG 라이브 (내가 RAG 역할)
    if verdict=="조례확인필요" and zone and sigungu:
        P(f"\n[조례 RAG·라이브] {sigungu} 도시계획조례 직접 조회...")
        jr=jorye_rag(sigungu,zone)
        P(f"  조례={jr.get('조례','?')} / 별표={jr.get('별표','?')}")
        P(f"  카페 가부={jr['상태']} ({jr.get('근거') or jr.get('사유')})")
        if jr.get("인용"): P(f"  인용: {jr['인용']}")
        P(f"  건폐율={jr.get('건폐율','?')} 용적률={jr.get('용적률','?')} (추출={jr.get('추출','?')} {jr.get('원문길이','?')}자)")
        verdict={"가능":"가능(조례 BodyText)","불가":"불가(조례 별표)"}.get(jr["상태"],"확인필요")
        P(f"  → 최종판정: {verdict}")
    if not verdict.startswith("가능"):
        P(f"[서류] 판정='{verdict}' — 가능 아님 → 서류 생략(가능 확정시만 워크플로우)."); return "\n".join(log)
    # 서류 = 라이브 전수 (라우팅 시드)
    stages=["건축허가"]
    if jimok in JIMOK_UIJAE: stages.append(JIMOK_UIJAE[jimok])
    if jimok in JIMOK_UIJAE or jimok=="잡종지": stages.append("개발행위")
    stages+=["착공신고","사용승인"]
    P(f"\n[워크플로우 단계] {' → '.join(stages)}")
    for st in stages:
        d=DOC.docs_for(st)
        if d["상태"]=="전수확보":
            P(f"\n■ {st} ({d['법령']} {d['조']}) 호 {d['건수']}개 [라이브 전수]")
            for x in d["서류"]: P(f"   {x['호']} {x['서류'][:60]}"+("[단서]" if x['단서있음'] else ""))
        else: P(f"\n▷ {st} [{d['상태']}] {d.get('사유')}")
    # 규제효과 라이브
    P("\n[규제효과 — 라이브 법령조회]")
    for g in REG.resolve(regs):
        if g["상태"]=="근거확보": P(f"   {g['규제']} → {g['법령']} {g['조']}({g['제목']})")
        else: P(f"   {g['규제']} → [기권] {g['근거'][:45]}")
    # 작성주체 라이브
    au=RM.author_rule(area,"신축")
    P(f"\n[작성주체·라이브 건축법§23①] {au['이번_케이스']} — {au['사유']}")
    return "\n".join(log)

if __name__=="__main__":
    a=sys.argv[1]; t=sys.argv[2] if len(sys.argv)>2 else "parcel"
    ar=int(sys.argv[3]) if len(sys.argv)>3 else 264
    uc=sys.argv[4] if len(sys.argv)>4 else "카페(일반음식점)"
    txt=run(a,t,ar,uc)
    fn=f"CASE_live_{re.sub(r'[^가-힣0-9]','_',a)[:20]}.md"
    open(fn,"w",encoding="utf-8").write("# 무하드코딩 라이브 e2e 결과\n\n```\n"+txt+"\n```\n")
    print("\n>>> 저장:",fn)
