# -*- coding: utf-8 -*-
"""첨부서류 = agent-loop 라이브 전수 fetch. wf_data 하드코딩 list 대체.
하이브리드: 시드(어느 시행규칙 어느 조 보나=법령구조 인덱스) + DRF 라이브 fetch로 호 전수.
서류명 하드코딩 0 — 전부 조문 원문. 법이 호 단위 명시 → 전수=누락0."""
import re
import law_fetch as L

# 시드 = 단계/의제 → (시행규칙명, 조문번호, 항번호 or None). '어느 조 보나'만.
DOC_SOURCE = {
 "건축허가": ("건축법 시행규칙", "6", "①"),
 "착공신고": ("건축법 시행규칙", "14", None),
 "사용승인": ("건축법 시행규칙", "16", None),
 "농지전용": ("농지법 시행규칙", "26", "②"),
 "개발행위": ("국토의 계획 및 이용에 관한 법률 시행규칙", "9", "①"),
 "산지전용": ("산지관리법 시행규칙", "10", "②"),
}

# 조건부 마커 = 법 작성관례("~경우로 한정/경우만 해당/해당 사항이 있는 경우" = 해당시만 제출).
# '다만' 단서와 별개: 단서=내용수정, 조건부=서류 자체가 선택. 하드코딩 아님(조문 원문 파싱).
_COND = ("한정한다", "경우만 해당", "해당 사항이 있는 경우", "해당하는 경우", "경우에 한한다", "경우에 한정", "경우로 한정")
def _is_cond(t): return any(m in t for m in _COND)
def _AL(v): return v if isinstance(v, list) else ([] if v is None else [v])
def _S(v):
    if v is None: return ''
    if isinstance(v, list): return ' '.join(_S(x) for x in v)
    if isinstance(v, dict): return _S(v.get('항내용') or v.get('호내용') or v.get('목내용') or '')
    return str(v)

_lawcache = {}
def _law(lawnm):
    if lawnm in _lawcache: return _lawcache[lawnm]
    r = L.search(lawnm, 'law')['LawSearch']['law']
    if isinstance(r, dict): r = [r]
    cand = [x for x in r if x.get('법령명한글') == lawnm]
    j = L.service(cand[0]['법령일련번호'], 'law') if cand else None
    _lawcache[lawnm] = j
    return j

DL = "https://www.law.go.kr"
# 별지서식 참조 파서: "별지 제1호의4서식"→(1,4), "별지 제13호서식"→(13,0). 법 작성관례 포맷파싱(과적합 아님).
_FORM_RE = re.compile(r"별지\s*제(\d+)호(?:의(\d+))?서식")

def _forms_index(법):
    """법령 별표단위 중 서식(form) → 다운로드 링크 인덱스. (별표번호,가지번호)→{제목,hwp,pdf}."""
    out = {}
    bt = 법.get("별표", {})
    for b in (_AL(bt.get("별표단위")) if isinstance(bt, dict) else []):
        if not isinstance(b, dict) or "서식" not in _S(b.get("별표구분")): continue
        try: no = int(_S(b.get("별표번호")) or 0)
        except (TypeError, ValueError): continue
        try: ga = int(_S(b.get("별표가지번호")) or 0)
        except (TypeError, ValueError): ga = 0
        hwp = (_S(b.get("별표서식파일링크")).split() or [""])[0]
        pdf = (_S(b.get("별표서식PDF파일링크")).split() or [""])[0]
        out[(no, ga)] = {"제목": _S(b.get("별표제목")),
                         "hwp": (DL + hwp) if hwp else "", "pdf": (DL + pdf) if pdf else ""}
    return out

def _ref_form(txt, forms):
    """텍스트의 첫 '별지 제X호(의Y)서식' 참조 → 해당 form 다운로드(없으면 None)."""
    for no, ga in _FORM_RE.findall(txt):
        key = (int(no), int(ga) if ga else 0)
        if key in forms: return forms[key]
    return None

def docs_for(stage):
    """단계명 → 시행규칙 조문 라이브 fetch → 첨부서류 호 전수."""
    if stage not in DOC_SOURCE:
        return {"단계": stage, "상태": "확인필요", "사유": "시드 미등록"}
    lawnm, jo, hang = DOC_SOURCE[stage]
    j = _law(lawnm)
    if not j:
        return {"단계": stage, "상태": "확인필요", "사유": f"{lawnm} fetch 실패"}
    법 = j['법령']
    forms = _forms_index(법)
    for u in _AL(법['조문']['조문단위']):
        if isinstance(u, dict) and str(u.get('조문번호')) == str(jo) and u.get('조문여부') == '조문':
            # 대상 항 찾기 (항 지정시 그 항, 없으면 조문직속 호 또는 첫 항)
            target_ho = []
            hangs = _AL(u.get('항'))
            if hang:
                for h in hangs:
                    if isinstance(h, dict) and h.get('항번호') == hang:
                        target_ho = _AL(h.get('호')); break
            if not target_ho:  # 항 직속 호 없으면 조문 직속 또는 첫 항
                target_ho = _AL(u.get('호')) or (_AL(hangs[0].get('호')) if hangs else [])
            # 주신청서 = 조문 전체(조문내용+전 항)의 첫 별지서식 참조 — 신청서 항과 첨부서류 항이 다를 수 있음
            jo_txt = _S(u.get('조문내용')) + ' ' + ' '.join(_S(h.get('항내용')) for h in hangs if isinstance(h, dict))
            신청서 = _ref_form(jo_txt, forms)   # 주신청서 양식(다운로드 링크)
            서류 = []
            for ho in target_ho:
                if not isinstance(ho, dict): continue
                num = _S(ho.get('호번호'))
                txt = ' '.join(_S(ho.get('호내용')).split())
                # 서류명 = 호 첫 문장(다만 단서 전까지)
                head = txt.split('. 다만')[0].split('다만,')[0].strip()
                if head.startswith('삭제'): continue   # 폐지된 호 제외
                ho_cond = _is_cond(txt)
                서류.append({"호": num, "서류": head[:80], "단서있음": '다만' in txt,
                            "조건부": ho_cond, "서식": _ref_form(txt, forms)})
                for mok in _AL(ho.get("목")):   # #1 "다음 각 목" 케이스 — 목까지 전수(조건부는 부모 호 상속)
                    if isinstance(mok, dict):
                        mtxt = ' '.join(_S(mok.get("목내용")).split())
                        if mtxt and not mtxt.startswith('삭제'):
                            서류.append({"호": num + _S(mok.get("목번호")), "서류": mtxt[:80],
                                        "단서있음": '다만' in mtxt, "조건부": ho_cond or _is_cond(mtxt),
                                        "서식": _ref_form(mtxt, forms)})
            return {"단계": stage, "법령": lawnm, "조": f"제{jo}조{hang or ''}",
                    "상태": "전수확보", "건수": len(서류), "신청서": 신청서, "서류": 서류}
    return {"단계": stage, "상태": "확인필요", "사유": f"제{jo}조 조문 못찾음"}

if __name__ == "__main__":
    import sys
    stages = sys.argv[1:] or ["건축허가", "농지전용", "개발행위", "착공신고", "사용승인"]
    for st in stages:
        r = docs_for(st)
        if r["상태"] == "전수확보":
            print(f"\n■ {r['단계']} ({r['법령']} {r['조']}) — 호 {r['건수']}개 라이브 전수")
            for d in r["서류"]:
                print(f"   {d['호']} {d['서류']}" + ("  [단서有]" if d['단서있음'] else ""))
        else:
            print(f"\n▷ {st} — [{r['상태']}] {r.get('사유')}")
