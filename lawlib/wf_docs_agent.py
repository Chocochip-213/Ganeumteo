# -*- coding: utf-8 -*-
"""첨부서류 = agent-loop 라이브 전수 fetch. wf_data 하드코딩 list 대체.
하이브리드: 시드(어느 시행규칙 어느 조 보나=법령구조 인덱스) + DRF 라이브 fetch로 호 전수.
서류명 하드코딩 0 — 전부 조문 원문. 법이 호 단위 명시 → 전수=누락0."""
import re
import law_fetch as L

# stub(비-LLM 테스트 스캐폴드) 전용 시드: 단계 → (시행규칙명, 조, 항). _UIJAE/_PERMIT처럼 비-LLM 결정용 고정 데이터.
DOC_SOURCE = {
 "건축허가": ("건축법 시행규칙", "6", "①"),
 "착공신고": ("건축법 시행규칙", "14", None),
 "사용승인": ("건축법 시행규칙", "16", None),
 "농지전용": ("농지법 시행규칙", "26", "②"),
 "개발행위": ("국토의 계획 및 이용에 관한 법률 시행규칙", "9", "①"),
 "산지전용": ("산지관리법 시행규칙", "10", "②"),
}
# ↑ stub 전용. 실 LLM 경로는 에이전트가 fetch한 law_name·article을 docs_for_stage에 직접 넘김
#   → docs_for엔 절차→법조 하드코딩 맵 없음(과적합 0, ANY 절차 범용).

# 조건부 마커 = 법 작성관례("~경우로 한정/경우만 해당/해당 사항이 있는 경우" = 해당시만 제출).
# '다만' 단서와 별개: 단서=내용수정, 조건부=서류 자체가 선택. 하드코딩 아님(조문 원문 파싱).
_COND = ("한정한다", "경우만 해당", "해당 사항이 있는 경우", "해당하는 경우", "경우에 한한다", "경우에 한정", "경우로 한정")
def _is_cond(t): return any(m in t for m in _COND)
# cross_ref = 관계 법령(의제 등)에 위임된 제출물 — 그 법의 신청서·구비서류로 갈음(이 단계 아닌 의제 단계서 해소). 법 작성관례 마커(서류명 맵 아님).
_XREF = ("제출하도록 의무화", "관계 법령에서 제출", "관계 법령에 따라 제출")
def _is_xref(t): return any(m in t for m in _XREF)
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

# 단계 시점·의미 근거 = 건축법 본법 조(허가/착공/사용승인). 라우팅 시드(법령구조 인덱스) — 사실은 fetch.
WHEN_SRC = {"건축허가": "11", "착공신고": "21", "사용승인": "22"}

def _when(stage):
    """단계 시점·의미 = 건축법 본법 해당 조 라이브 fetch. 조문제목=의미, 조문내용+①항=시점 인용(hover용)."""
    jo = WHEN_SRC.get(stage)
    if not jo: return {}
    j = _law("건축법")
    if not j: return {}
    for u in _AL(j['법령']['조문']['조문단위']):
        if isinstance(u, dict) and str(u.get('조문번호')) == jo and u.get('조문여부') == '조문':
            parts = [_S(u.get('조문내용'))]
            for h in _AL(u.get('항'))[:1]:
                if isinstance(h, dict): parts.append(_S(h.get('항내용')))
            body = ' '.join(' '.join(parts).split())
            body = re.sub(r"<(개정|신설|본조신설|전문개정)[^>]*>", "", body).strip()   # 개정마커 제거(알려진 주석구조)
            return {"when_law": f"건축법 제{jo}조", "when_title": _S(u.get('조문제목')), "when_quote": body[:200]}
    return {}

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

def docs_for(stage, law_name=None, article=None, hang_override=None):
    """단계 → 시행규칙 조문 라이브 fetch → 첨부서류 호 전수.
    법령·조는 호출자가 지정: 실 LLM 경로=에이전트가 fetch해 확인한 law_name·article 전달 / stub=스캐폴드 시드 전달.
    docs_for 자체엔 절차→법조 하드코딩 맵 없음 → ANY 절차 범용."""
    if not (law_name and article):
        return {"단계": stage, "상태": "확인필요", "사유": "법령·조 미지정(law_name·article 필요)"}
    lawnm, jo, hang = law_name, str(article).replace("제", "").replace("조", "").strip(), hang_override
    j = _law(lawnm)
    if not j:
        return {"단계": stage, "상태": "확인필요", "사유": f"{lawnm} fetch 실패"}
    법 = j['법령']
    forms = _forms_index(법)
    _jm = re.match(r'(\d+)(?:의(\d+))?', str(jo))   # '12의2'→조문번호12·조문가지번호2 분리(조의X 지원)
    jo_num, jo_ga = (_jm.group(1), _jm.group(2) or '') if _jm else (str(jo), '')
    for u in _AL(법['조문']['조문단위']):
        if isinstance(u, dict) and str(u.get('조문번호')) == jo_num and (not jo_ga or str(u.get('조문가지번호') or '') == jo_ga) and u.get('조문여부') == '조문':
            # 대상 항 찾기 (항 지정시 그 항, 없으면 조문직속 호 또는 첫 항)
            target_ho = []
            hangs = _AL(u.get('항'))
            _hang_ok = True   # item 5: 명시 hang이 실제 매칭됐나 — 불일치면 fallback이라 전수확보 금지(엉뚱 조문 오판 방지)
            if hang:
                _hang_ok = False
                for h in hangs:
                    if isinstance(h, dict) and h.get('항번호') == hang:
                        target_ho = _AL(h.get('호')); _hang_ok = True; break
            if not target_ho:  # 항 미지정/미발견: 조문 직속 호, 없으면 '호를 가진 첫 항'(농지 §26처럼 ②항에 서류 있는 경우 대응)
                target_ho = _AL(u.get('호'))
                if not target_ho:
                    for h in hangs:
                        if isinstance(h, dict) and _AL(h.get('호')):
                            target_ho = _AL(h.get('호')); break
            # 주신청서 = 조문 전체(조문내용+전 항)의 첫 별지서식 참조 — 신청서 항과 첨부서류 항이 다를 수 있음
            jo_txt = _S(u.get('조문내용')) + ' ' + ' '.join(_S(h.get('항내용')) for h in hangs if isinstance(h, dict))
            신청서 = _ref_form(jo_txt, forms)   # 주신청서 양식(다운로드 링크)
            서류 = []
            for ho in target_ho:
                if not isinstance(ho, dict): continue
                txt = ' '.join(_S(ho.get('호내용')).split())
                _hm = re.match(r'^(\d+(?:의\d+)?)\s*\.', txt)   # 호내용 앞 라벨 = 권위(API 호번호가 '1의2'를 '1.'로 collapse → 안정 식별자 복원, 검수 #4)
                num = (_hm.group(1) + ".") if _hm else _S(ho.get('호번호'))
                # 서류명 = 호 첫 문장(다만 단서 전까지)
                head = txt.split('. 다만')[0].split('다만,')[0].strip()
                if re.match(r'^[\d의.\s]*삭제', head): continue   # 폐지된 호 제외(호내용 '4. 삭제 <…>'처럼 호번호 접두 붙는 경우 포함)
                ho_cond = _is_cond(txt)
                moks = [m for m in _AL(ho.get("목")) if isinstance(m, dict)]
                # item_type = 법령 구조서 도출(무하드코딩, 서류명 맵 아님): cross_ref(관계법령 위임) > group('각 목' 헤더, 목이 실제 제출물) > doc
                if _is_xref(txt):
                    ho_type = "cross_ref"
                elif moks and "각 목" in head:   # 본문절(다만 前) 기준 — '각 목'이 다만 단서(대체수단)에 있으면 그 호는 group이 아니라 doc(목=대체 spec)
                    ho_type = "group"
                else:
                    ho_type = "doc"
                서류.append({"호": num, "서류": head, "단서있음": '다만' in txt,
                            "조건부": ho_cond, "서식": _ref_form(txt, forms), "유형": ho_type})
                mok_type = "doc" if ho_type == "group" else "spec"   # 그룹헤더 하위=제출 peer / 일반 호 하위=세부명세(들여쓰기)
                for mok in moks:   # #1 "다음 각 목" 케이스 — 목까지 전수(조건부는 부모 호 상속)
                    mtxt = ' '.join(_S(mok.get("목내용")).split())
                    if mtxt and not mtxt.startswith('삭제'):
                        서류.append({"호": num + _S(mok.get("목번호")), "서류": mtxt,
                                    "단서있음": '다만' in mtxt, "조건부": ho_cond or _is_cond(mtxt),
                                    "서식": _ref_form(mtxt, forms),
                                    "유형": "cross_ref" if _is_xref(mtxt) else mok_type})
            _st = "확인필요" if (hang and not _hang_ok) else "전수확보"   # item 5: 명시 항 불일치 fallback은 확정(전수확보) 금지
            return {"단계": stage, "법령": lawnm, "조": f"제{jo_num}조" + (f"의{jo_ga}" if jo_ga else "") + (hang or ''),
                    "상태": _st, "사유": (f"명시 항 '{hang}' 불일치 — fallback 수집(확정 아님)" if _st == "확인필요" else ""),
                    "건수": len(서류), "신청서": 신청서, "서류": 서류, **_when(stage)}
    return {"단계": stage, "상태": "확인필요", "사유": f"제{jo_num}조{('의' + jo_ga) if jo_ga else ''} 조문 못찾음"}

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
