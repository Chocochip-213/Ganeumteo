# -*- coding: utf-8 -*-
"""빌드타임 조례 인덱서 (에이전트 루프 밖, uv run). 데모 4지자체 × 도시계획조례 용도지역 별표.
검수: 도시계획만(title-regex 전용, fix#2/#3) · area_cd5 저장(fix#6) · utf-8 콘솔(fix#8) · 별표 데이터주도 전수(0/1/N) · hwpx PK-magic SKIP · OK/SKIP/MISS 정직 로그."""
import sys, re, io, zlib, time, zipfile, urllib.request
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\kmw16\Desktop\agent\probe\ganeomteo")
sys.path.insert(0, r"C:\Users\kmw16\Desktop\agent\probe\research")
import olefile
import law_fetch as L
from infra.embed import embed_batch
from infra import db

# 경기 남부 전체 + 춘천. (검색 토큰, area_cd5 시군구코드[메타·구있는시는 부정확], 표시명).
# 키링은 sigungu_org LIKE(토큰) — 구 있는 시는 PNU[:5]=구코드라 area_cd5 매칭 불가, 토큰이 정답.
DEMO = [("수원시", "41110", "경기도 수원시"), ("성남시", "41130", "경기도 성남시"),
        ("용인시", "41460", "경기도 용인시"), ("화성시", "41590", "경기도 화성시"),
        ("평택시", "41220", "경기도 평택시"), ("안산시", "41270", "경기도 안산시"),
        ("안양시", "41170", "경기도 안양시"), ("부천시", "41190", "경기도 부천시"),
        ("광명시", "41210", "경기도 광명시"), ("시흥시", "41390", "경기도 시흥시"),
        ("군포시", "41410", "경기도 군포시"), ("의왕시", "41430", "경기도 의왕시"),
        ("과천시", "41290", "경기도 과천시"), ("오산시", "41370", "경기도 오산시"),
        ("안성시", "41550", "경기도 안성시"), ("이천시", "41500", "경기도 이천시"),
        ("여주시", "41670", "경기도 여주시"), ("양평군", "41830", "경기도 양평군"),
        ("하남시", "41450", "경기도 하남시"), ("광주시", "41610", "경기도 광주시"),
        ("김포시", "41570", "경기도 김포시"), ("남양주시", "41360", "경기도 남양주시"),
        ("춘천시", "51110", "강원특별자치도 춘천시")]
ORDIN_KIND = "도시계획"
EMB_CAP = 7000          # 임베딩 입력 상한(text-embedding-3-large 8191 토큰 안전마진)


def _clean(full):
    return re.sub(r"\s+", " ", re.sub(r"[^가-힣0-9().,ㆍ· ]", " ", full)).strip()


def _extract_hwp_ole(raw):
    """.hwp(OLE) → BodyText/Section0 (zlib raw deflate -15), PrvText fallback."""
    o = olefile.OleFileIO(io.BytesIO(raw))
    try:
        secs = sorted([s for s in o.listdir() if len(s) > 1 and s[0] == "BodyText"], key=lambda s: s[1])
        if secs:
            parts = []
            for s in secs:
                d = o.openstream(s).read()
                try:
                    parts.append(zlib.decompress(d, -15).decode("utf-16-le", "ignore"))
                except Exception:
                    parts.append(d.decode("utf-16-le", "ignore"))
            return _clean(" ".join(parts)), "BodyText"
        return _clean(o.openstream("PrvText").read().decode("utf-16-le", "ignore")), "PrvText(캡)"
    finally:
        o.close()


def _extract_hwpx_zip(raw):
    """.hwpx(zip) → Contents/section*.xml의 <t> 텍스트 추출."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    secs = sorted(n for n in z.namelist() if re.search(r"section\d+\.xml$", n, re.I))
    if not secs:
        secs = sorted(n for n in z.namelist() if n.lower().endswith(".xml") and "content" in n.lower())
    parts = []
    for n in secs:
        xml = z.read(n).decode("utf-8", "ignore")
        parts += re.findall(r"<(?:\w+:)?t\b[^>]*>(.*?)</(?:\w+:)?t>", xml, re.S)
    text = re.sub(r"<[^>]+>", " ", " ".join(parts))
    return _clean(text), "hwpx"


def _extract_bodytext(url):
    raw = None
    for _ in range(4):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0", "Connection": "close"}), timeout=40).read()
            break
        except Exception:
            time.sleep(1.5)
    if not raw:
        return None, "DOWNLOAD_FAIL"
    try:
        if raw[:4] == bytes.fromhex("d0cf11e0"):       # .hwp (OLE)
            text, method = _extract_hwp_ole(raw)
        elif raw[:2] == b"PK":                          # .hwpx (zip) — 검수 후 추가
            text, method = _extract_hwpx_zip(raw)
        else:
            return None, "UNKNOWN_FMT"
    except Exception as e:
        return None, f"EXTRACT_FAIL({type(e).__name__})"
    return (text or None), method


_EXCL = ("노후", "정비", "사전협상", "변경", "경관", "주차", "재정비", "위원회", "시행")


def _pick_ordin(items, token):
    """진짜 '도시(·군)계획 조례'를 집는다. 노후계획도시·사전협상 등 distractor 배제."""
    named = [it for it in items if token in str(it.get("자치법규명", ""))]
    norm = lambda it: re.sub(r"\s+", " ", str(it.get("자치법규명", "")))
    for pat in ("도시계획 조례", "도시·군계획 조례", "도시군계획 조례", "도시ㆍ군계획 조례", "도시계획조례"):
        hit = [it for it in named if pat in norm(it)]
        if hit:
            return hit[0]
    cl = [it for it in named if "도시계획" in norm(it) and not any(e in norm(it) for e in _EXCL)]
    if cl:
        return cl[0]
    return named[0] if named else (items[0] if items else None)


def index_one(token, area_cd5):
    s = L.ordin_search(f"{token} 도시계획")
    items = s.get("items") or []
    c0 = _pick_ordin(items, token)
    if not c0:
        print(f"MISS {token}: 도시계획조례 검색 0건"); return []
    mst = c0.get("자치법규일련번호") or c0.get("MST")
    nm = str(c0.get("자치법규명", ""))
    j = L.ordin_service(mst)
    bu = j.get("별표", {}).get("별표단위") or []
    if isinstance(bu, dict):
        bu = [bu]
    targets = [b for b in bu if isinstance(b, dict) and
               ("건축할 수 있는" in str(b.get("별표제목", "")) or "건축할 수 없는" in str(b.get("별표제목", "")))]
    if not targets:
        print(f"MISS {token}: '건축할 수 있는/없는' 용도지역 별표 0건 (조례={nm})"); return []
    texts, metas = [], []
    for b in targets:
        title = str(b.get("별표제목", "")); bno = str(b.get("별표번호", "")); url = str(b.get("별표첨부파일명", ""))
        if not url:
            print(f"SKIP {token} 별표{bno} '{title[:20]}': 첨부 없음"); continue
        text, method = _extract_bodytext(url)
        if not text:
            print(f"SKIP {token} 별표{bno} '{title[:20]}': {method}"); continue
        mz = re.search(r"\]\s*(.+?)\s*안에서", title)        # "[별표N] <용도지역>안에서…" → 정확 zone(제N종 포함)
        if mz:
            zone = mz.group(1).strip()
        else:
            mz2 = re.search(r"([가-힣0-9]+지역|[가-힣]+지구)", title)
            zone = mz2.group(1) if mz2 else (title[:20] or "용도지역")
        texts.append(text); metas.append((bno, title, zone, method, nm, str(mst)))
        print(f"OK   {token} 별표{bno} '{title[:24]}' zone={zone} {method} {len(text)}자")
    if not texts:
        return []
    vecs = embed_batch([t[:EMB_CAP] for t in texts])
    rows = []
    for (bno, title, zone, method, nm_, mst_), text, vec in zip(metas, texts, vecs):
        rows.append({"chunk_id": f"{area_cd5}:{ORDIN_KIND}:별표{bno}", "area_cd5": area_cd5,
                     "sigungu_org": nm_, "ordin_name": nm_, "ordin_mst": mst_, "ordin_kind": ORDIN_KIND,
                     "chunk_type": "별표", "byeolpyo_no": bno, "byeolpyo_title": title[:120], "zone": zone,
                     "eff_date": None, "extract_method": method, "src_len": len(text), "body": text, "embedding": vec})
    return rows


def main():
    all_rows = []
    for token, area_cd5, full in DEMO:
        print(f"\n=== {full} ({area_cd5}) ===")
        try:
            all_rows += index_one(token, area_cd5)
        except Exception as e:
            print(f"ERROR {token}: {type(e).__name__}: {e}")
    n = db.upsert_chunks(all_rows)
    print(f"\n=== upserted {n} chunks ===")
    with db.connect() as c:
        for area, sg, cnt in c.execute(
                "SELECT area_cd5, max(sigungu_org), count(*) FROM ordin_chunk GROUP BY area_cd5 ORDER BY 1").fetchall():
            print(f"  index: area={area} ({sg}) chunks={cnt}")


if __name__ == "__main__":
    main()
