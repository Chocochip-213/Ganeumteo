#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""law.go.kr DRF fetch helper. cp949 decode + retry/backoff. WinError 10054 prone."""
import urllib.request, urllib.parse, json, time, sys

OC = "openlawSSAFYkey"
BASE = "http://www.law.go.kr/DRF"

import io as _io, zlib as _zlib
try:
    import olefile as _olefile
except ImportError:
    _olefile = None

_HWP_EXT_CTRL = {1, 2, 3, 4, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23}   # 8-wchar 확장 인라인컨트롤


def _hwp_para_text(payload):
    chars = []; i = 0; n = len(payload)
    while i + 2 <= n:
        wc = int.from_bytes(payload[i:i + 2], "little"); i += 2
        if wc in _HWP_EXT_CTRL:
            i += 14                       # 컨트롤=8 wchar → 뒤 7개(14B) param skip
        elif wc < 32:
            if wc in (9, 10, 13): chars.append(" ")
        else:
            chars.append(chr(wc))
    return "".join(chars)


def hwp_ole_text(raw):
    """.hwp(OLE) BodyText/SectionN의 PARA_TEXT(tag 67) 레코드만 추출 → 깨끗한 텍스트.
    통째 utf-16 디코드는 레코드 헤더(바이너리)까지 디코드해 쓰레기 → 레코드 파싱 필수. 못 뽑으면 None."""
    if _olefile is None:
        return None
    try:
        o = _olefile.OleFileIO(_io.BytesIO(raw))
    except Exception:
        return None
    try:
        secs = sorted([s for s in o.listdir() if len(s) > 1 and s[0] == "BodyText"], key=lambda s: s[1])
        out = []
        for s in secs:
            d = o.openstream(s).read()
            try:
                stream = _zlib.decompress(d, -15)
            except Exception:
                stream = d
            i = 0; n = len(stream)
            while i + 4 <= n:
                hdr = int.from_bytes(stream[i:i + 4], "little"); i += 4
                tag = hdr & 0x3FF; size = (hdr >> 20) & 0xFFF
                if size == 0xFFF:
                    if i + 4 > n: break
                    size = int.from_bytes(stream[i:i + 4], "little"); i += 4
                data = stream[i:i + size]; i += size
                if tag == 67:                 # HWPTAG_PARA_TEXT
                    out.append(_hwp_para_text(data))
        return (" ".join(out).strip() or None)
    finally:
        o.close()


def hwpx_text(raw):
    """.hwpx(zip) Contents/sectionN.xml의 <t> 텍스트 추출. 못 뽑으면 None."""
    import zipfile, re as _re
    try:
        z = zipfile.ZipFile(_io.BytesIO(raw))
    except Exception:
        return None
    secs = sorted(n for n in z.namelist() if _re.search(r"section\d+\.xml$", n, _re.I))
    if not secs:
        secs = sorted(n for n in z.namelist() if n.lower().endswith(".xml") and "content" in n.lower())
    parts = []
    for n in secs:
        xml = z.read(n).decode("utf-8", "ignore")
        parts += _re.findall(r"<(?:\w+:)?t\b[^>]*>(.*?)</(?:\w+:)?t>", xml, _re.S)
    text = _re.sub(r"<[^>]+>", " ", " ".join(parts))
    return (text.strip() or None)


def byeolpyo_text(raw):
    """별표 첨부(.hwp OLE 또는 .hwpx zip) → 깨끗한 텍스트. 포맷 자동감지. 못 뽑으면 None."""
    if not raw:
        return None
    if raw[:4] == b"\xd0\xcf\x11\xe0":     # OLE = .hwp
        return hwp_ole_text(raw)
    if raw[:2] == b"PK":                    # zip = .hwpx
        return hwpx_text(raw)
    return None

def _get(url, tries=6, sleep=2.0):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "*/*", "Connection": "close"})
            raw = urllib.request.urlopen(req, timeout=40).read()
            # law.go.kr DRF JSON is cp949
            try:
                return raw.decode("cp949")
            except UnicodeDecodeError:
                return raw.decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(sleep * (i + 1))
    raise last

def search(query, target="law"):
    q = urllib.parse.quote(query)
    url = f"{BASE}/lawSearch.do?OC={OC}&target={target}&type=JSON&query={q}"
    return json.loads(_get(url))

def service(mst, target="law"):
    url = f"{BASE}/lawService.do?OC={OC}&target={target}&MST={mst}&type=JSON"
    return json.loads(_get(url))

def service_id(law_id, target="law"):
    url = f"{BASE}/lawService.do?OC={OC}&target={target}&ID={law_id}&type=JSON"
    return json.loads(_get(url))

# --- 자치법규(조례) — 실측 확인 2026-05-28 ---
# search 응답 노드 = OrdinSearch (law/service 는 LawSearch/LawService).
# search item 필드: 자치법규명, 지자체기관명(=WHERE 키), 자치법규일련번호(MST), 시행일자.
# service 노드: 자치법규기본정보, 별표, 부칙, 조문{조:[{조문번호,조제목,조내용,조문여부}]}, 제개정이유.
def ordin_search(query, display=20, page=1):
    q = urllib.parse.quote(query)
    url = f"{BASE}/lawSearch.do?OC={OC}&target=ordin&type=JSON&query={q}&display={display}&page={page}"
    s = json.loads(_get(url))["OrdinSearch"]
    arr = s.get("law", [])
    if isinstance(arr, dict):
        arr = [arr]
    return {"totalCnt": s.get("totalCnt"), "items": arr}

def ordin_service(mst):
    url = f"{BASE}/lawService.do?OC={OC}&target=ordin&MST={mst}&type=JSON"
    return json.loads(_get(url))["LawService"]

def ordin_articles(mst):
    """조례 본문을 (조제목, 조내용) 리스트로 평탄화 — RAG 청킹용."""
    j = ordin_service(mst)
    jo = j.get("조문", {})
    arr = jo.get("조", []) if isinstance(jo, dict) else []
    if isinstance(arr, dict):
        arr = [arr]
    out = []
    for a in arr:
        if isinstance(a, dict) and a.get("조문여부") == "Y":
            out.append((a.get("조제목", ""), a.get("조내용", "")))
    return out

if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "search":
        print(json.dumps(search(sys.argv[2], sys.argv[3] if len(sys.argv)>3 else "law"), ensure_ascii=False)[:3000])
    elif cmd == "service":
        print(json.dumps(service(sys.argv[2], sys.argv[3] if len(sys.argv)>3 else "law"), ensure_ascii=False)[:3000])
