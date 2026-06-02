# -*- coding: utf-8 -*-
"""하이브리드 인허가 로드맵 생성기.
결정적 라우팅(지목·용도지역·면적 → 어느 법/조 보나) + 라이브 tool fetch(서류·규제·작성주체).
하드코딩=라우팅 시드만(법령구조 인덱스). 사실(서류·근거·효과)=전부 DRF fetch. 못찾으면 기권.
일관성=사실이 fetch에 고정되므로 동일입력→동일출력(LLM 판단 배제)."""
import json, sys
import wf_docs_agent as DOC
import wf_reg_agent as REG
import law_fetch as L

# 결정적 라우팅 시드: 지목 → 전용 의제 (어느 법 보나)
JIMOK_UIJAE = {"전": "농지전용", "답": "농지전용", "과수원": "농지전용", "임야": "산지전용"}

def _AL(v): return v if isinstance(v, list) else ([] if v is None else [v])
def _S(v):
    if v is None: return ''
    if isinstance(v, list): return ' '.join(_S(x) for x in v)
    if isinstance(v, dict): return _S(v.get('항내용') or v.get('호내용') or '')
    return str(v)

def author_rule(연면적, 작업="신축"):
    """작성주체 = 건축법 §23① 원칙·단서 라이브 fetch(grounding만 반환, 가부 단정 안 함).
    면제 해당 여부('걸리나 안 걸리나')는 fetch한 단서 원문을 읽은 LLM/사람의 적용판단 몫 — 도구는 신호(원문)만."""
    a = L.search('건축법', 'law')['LawSearch']['law']
    if isinstance(a, dict): a = [a]
    mst = [x for x in a if x.get('법령명한글') == '건축법'][0]['법령일련번호']
    j = L.service(mst, 'law')
    원칙 = ""; 단서 = []
    for u in _AL(j['법령']['조문']['조문단위']):
        if isinstance(u, dict) and str(u.get('조문번호')) == '23' and u.get('조문여부') == '조문':
            for h in _AL(u.get('항')):
                if isinstance(h, dict) and h.get('항번호') == '①':
                    원칙 = ' '.join(_S(h.get('항내용')).split())[:200]   # 원칙=fetch한 ①항 원문(하드코딩 텍스트 제거)
                    for ho in _AL(h.get('호')):
                        단서.append(' '.join(_S(ho).split())[:80])       # 단서=fetch한 각 호 원문(면적임계 포함)
    if not 원칙 and not 단서:   # fetch 실패 → 확인필요 기권(날조 금지)
        return {"근거": "건축법 §23①", "상태": "확인필요", "원칙": "", "단서": [],
                "작업": 작업, "연면적": 연면적, "사유": "§23① 원문 미확보"}
    return {"근거": "건축법 §23①", "상태": "확보", "원칙": 원칙, "단서": 단서,
            "작업": 작업, "연면적": 연면적,
            "사유": f"{작업} 연면적 {연면적}㎡ — §23① 원칙·단서 원문 확보(면제 해당여부는 단서 원문 대조로 판단)"}

def roadmap(입지, 용도, 연면적, 층수, 작업="신축", 판정노트=""):
    지목 = 입지["지목"]; 규제 = 입지.get("규제", [])
    # 1) 결정적 라우팅: 의제 단계
    stages = ["건축허가"]
    if 지목 in JIMOK_UIJAE: stages.append(JIMOK_UIJAE[지목])
    if 지목 in JIMOK_UIJAE or 지목 in ("잡종지",): stages.append("개발행위")  # 형질변경
    stages += ["착공신고", "사용승인"]
    # 2) 라이브 서류 전수 fetch
    서류 = [DOC.docs_for(s) for s in stages]
    # 3) 규제효과 라이브 법령조회
    규제효과 = REG.resolve(규제)
    # 4) 작성주체 라이브
    작성 = author_rule(연면적, 작업)
    # 5) 조건부(면적임계 — 법정상수라 결정적 분기 유지). 서류명·근거는 코드 prose가 아니라
    #    시드(법령명+조번호=구조 포인터)로 조문 라이브 fetch해 파생, 실패시 확인필요(날조 금지).
    조건부 = []
    for need, (법령, 조) in (
            (연면적 >= 500, ("녹색건축물 조성 지원법", "14")),
            (연면적 >= 200 or 층수 >= 2, ("건축법", "48"))):
        if not need: continue
        art = REG._fetch_article(법령, 조)
        if art and art.get("제목"):
            조건부.append({"서류": art["제목"], "근거": f"{법령} {art['조']}", "상태": "확보"})
        else:
            조건부.append({"근거": f"{법령} 제{조}조", "상태": "확인필요"})
    return {"입지": 입지, "용도": 용도, "연면적": 연면적, "층수": 층수,
            "판정노트": 판정노트, "단계순서": stages, "서류_라이브전수": 서류,
            "규제효과_라이브": 규제효과, "작성주체_라이브": 작성, "조건부서류": 조건부}

if __name__ == "__main__":
    # ⚠️ PROTOTYPE/CLI 데모 (item 19): standalone 로드맵 출력은 운영 판정 경로 아님(fixture oracle로도 쓰지 말 것).
    #    운영은 REG.resolve(라우팅 힌트) 등 fetch만 쓰고 영향판정은 LLM(record_reg_resolution)이 한다.
    입지 = {"지목": "전", "용도지역": "자연녹지지역",
            "규제": ["비행안전제3구역", "생산녹지지역", "자연녹지지역", "가축사육제한구역"]}
    r = roadmap(입지, "카페(일반음식점)", 264, 1,
                판정노트="자연녹지 일반음식점=춘천조례 별표16 나목(제4호자목) 가능, 건폐20%/용적100%")
    if "--json" in sys.argv:
        print(json.dumps(r, ensure_ascii=False))
    else:
        print(f"=== 로드맵: {r['용도']} {r['연면적']}㎡ {r['층수']}층 / {입지['지목']}·{입지['용도지역']} ===")
        print("판정:", r["판정노트"])
        print("단계:", " → ".join(r["단계순서"]))
        for s in r["서류_라이브전수"]:
            if s["상태"] == "전수확보":
                print(f"\n■ {s['단계']} ({s['법령']} {s['조']}) 호 {s['건수']}개")
                for d in s["서류"]: print(f"   {d['호']} {d['서류'][:55]}" + ("[단서]" if d['단서있음'] else ""))
            else: print(f"\n▷ {s['단계']} [{s['상태']}] {s.get('사유')}")
        print("\n[규제효과 라이브 법령조회]")
        for g in r["규제효과_라이브"]:
            if g["상태"] == "근거확보": print(f"   {g['규제']} → {g['법령']} {g['조']}")
            else: print(f"   {g['규제']} → [기권] {g['근거'][:40]}")
        print(f"\n[작성주체] §23① 원칙: {r['작성주체_라이브'].get('원칙','')[:60]} — {r['작성주체_라이브']['사유']}")
        print("[조건부]", ", ".join(f"{c.get('서류','?')}({c['근거']}/{c['상태']})" for c in r["조건부서류"]) or "없음")
