# -*- coding: utf-8 -*-
"""규제효과 = agent-loop RAG. static dict(wf_data.REG_EFFECT) 대체.
규제명 → (시드: 어느 법이 규율하나) → DRF 라이브 fetch → 근거조문 원문 인용.
시드는 인덱스(어느 법 볼지)만, 효과 텍스트는 하드코딩 0 — 전부 fetch 원문.
못 찾으면 '확인필요' 기권(환각 금지). 의제 23종(wf_data.UIJAE)과 같은 철학."""
import law_fetch as L

# 시드 = 규제명 키워드 → (법령명, 조문번호). '어느 법 보나'만. 효과는 fetch.
REG_LAW = [
 ("비행안전",       "군사기지 및 군사시설 보호법", "10"),
 ("가축사육제한",   "가축분뇨의 관리 및 이용에 관한 법률", "8"),
 ("개발제한구역",   "개발제한구역의 지정 및 관리에 관한 특별조치법", "12"),
 ("상수원보호",     "수도법", "7"),
 ("농업진흥",       "농지법", "32"),
 ("보전산지",       "산지관리법", "12"),
 ("도시공원",       "도시공원 및 녹지 등에 관한 법률", "24"),
 ("자연공원",       "자연공원법", "23"),
 ("문화유산",       "문화유산의 보존 및 활용에 관한 법률", "13"),
 ("수산자원보호",   "수산자원관리법", "52"),
 ("토지거래",       "부동산 거래신고 등에 관한 법률", "11"),
 ("녹지지역",       "국토의 계획 및 이용에 관한 법률", "76"),
 ("관리지역",       "국토의 계획 및 이용에 관한 법률", "76"),
 ("주거지역",       "국토의 계획 및 이용에 관한 법률", "76"),
 ("상업지역",       "국토의 계획 및 이용에 관한 법률", "76"),
]

def _AL(v): return v if isinstance(v, list) else ([] if v is None else [v])
def _S(v):
    if v is None: return ''
    if isinstance(v, list): return ' '.join(_S(x) for x in v)
    if isinstance(v, dict): return _S(v.get('항내용') or v.get('호내용') or v.get('목내용') or '')
    return str(v)
def _cont(u):
    t = _S(u.get('조문내용'))
    for h in _AL(u.get('항')): t += ' ' + _S(h)
    return ' '.join(t.split())

_cache = {}
def _fetch_article(lawnm, jo):
    key = (lawnm, jo)
    if key in _cache: return _cache[key]
    out = None
    try:
        r = L.search(lawnm, 'law')['LawSearch']['law']
        if isinstance(r, dict): r = [r]
        cand = [x for x in r if x.get('법령명한글') == lawnm]
        if cand:
            j = L.service(cand[0]['법령일련번호'], 'law')
            for u in _AL(j['법령']['조문']['조문단위']):
                if isinstance(u, dict) and str(u.get('조문번호')) == str(jo) and u.get('조문여부') == '조문':
                    out = {"법령": lawnm, "조": f"제{jo}조", "제목": _S(u.get('조문제목')),
                           "원문": _cont(u)}
                    break
    except Exception as e:
        out = {"error": str(e)}
    _cache[key] = out
    return out

def resolve(reg_names, maxlen=200):
    """규제명 리스트 → 각각 DRF 라이브 조회 → 근거조문 인용 or 기권."""
    seen, results = set(), []
    for nm in reg_names:
        nm = str(nm or '').strip()
        if not nm: continue
        hit = next((t for t in REG_LAW if t[0] in nm), None)
        if not hit:
            results.append({"규제": nm, "상태": "확인필요", "근거": "시드 미등록 → 규제명 키워드 DRF 검색 fallback 필요"})
            continue
        _, lawnm, jo = hit
        if (lawnm, jo) in seen:  # 같은 조문 중복 규제(녹지/도시 등) 1회만
            continue
        seen.add((lawnm, jo))
        art = _fetch_article(lawnm, jo)
        if not art:
            results.append({"규제": nm, "상태": "확인필요", "근거": f"{lawnm} 제{jo}조 fetch 실패→기권"})
        elif art.get("error"):
            results.append({"규제": nm, "상태": "확인필요", "근거": f"조회오류:{art['error']}"})
        else:
            results.append({"규제": nm, "상태": "근거확보",
                            "법령": art["법령"], "조": art["조"], "제목": art["제목"],
                            "인용": art["원문"][:maxlen]})
    return results

if __name__ == "__main__":
    import sys
    regs = sys.argv[1:] or ["비행안전제3구역", "도시지역", "생산녹지지역", "자연녹지지역", "가축사육제한구역"]
    for r in resolve(regs):
        if r["상태"] == "근거확보":
            print(f"▶ {r['규제']}  →  {r['법령']} {r['조']}({r['제목']})")
            print(f"   {r['인용']}")
        else:
            print(f"▷ {r['규제']}  →  [{r['상태']}] {r['근거']}")
