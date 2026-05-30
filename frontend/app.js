// 오케스트레이터: 폼 → SSE(EventSource) → 트레이스 dispatch → done이면 결과 fetch → 카드. HITL 지원.
import { appendTrace, resetTrace } from "./trace.js";
import { renderCard } from "./card.js";

const $ = (s) => document.querySelector(s);
let threadId = null, es = null;

function setBusy(b) { const g = $("#go"); g.disabled = b; g.textContent = b ? "진단 중…" : "진단 시작"; }

function openStream(url) {
  if (es) es.close();
  es = new EventSource(url);
  es.onmessage = (e) => {
    let ev; try { ev = JSON.parse(e.data); } catch { return; }
    if (ev.kind === "meta" && ev.detail && ev.detail.thread_id) threadId = ev.detail.thread_id;
    appendTrace(ev);
    if (ev.kind === "interrupt") { showHitl(ev.detail); return; }      // 스트림 멈춤 → 입력 폼
    if (ev.kind === "done") { es.close(); setBusy(false); fetchResult(); }
  };
  es.onerror = () => { if (es) es.close(); setBusy(false); };
}

function start(e) {
  e.preventDefault();
  const addr = $("#address").value.trim();
  if (!addr) { $("#address").focus(); return; }
  threadId = null;
  $("#hitl-wrap").innerHTML = "";
  $("#card").innerHTML = "<p class='placeholder'>진단 진행 중…<br><span class='spinner'></span></p>";
  resetTrace($("#trace"));
  setBusy(true);
  const qs = new URLSearchParams({
    address: addr,
    use_type: $("#use").value.trim() || "근린생활시설",
    floor_area: $("#area").value || "0",
    floor_count: $("#floors").value || "1",
  });
  openStream("/diagnose/stream?" + qs.toString());
}

async function fetchResult() {
  if (!threadId) return;
  try {
    const r = await fetch("/diagnose/result?thread_id=" + encodeURIComponent(threadId));
    const j = await r.json();
    renderCard($("#card"), j._return, j.citations);
    if (j.xy) renderMap(j.xy, j.address, j.jimok, j.zone);
  } catch (err) {
    $("#card").innerHTML = "<p class='placeholder'>결과를 불러오지 못했습니다.</p>";
  }
}

function showHitl(detail) {
  const fields = (detail && detail.fields) || ["floor_area", "floor_count", "use_type"];
  const labels = { floor_area: "연면적(㎡)", floor_count: "층수", use_type: "용도" };
  const wrap = $("#hitl-wrap");
  wrap.innerHTML = "";
  const box = document.createElement("div"); box.id = "hitl";
  const q = document.createElement("div");
  q.style.cssText = "margin-bottom:8px;font-weight:600";
  q.textContent = "✋ " + ((detail && detail.question) || "추가 입력이 필요합니다");
  box.appendChild(q);
  const inputs = {};
  fields.forEach((f) => {
    const i = document.createElement("input");
    i.placeholder = labels[f] || f; inputs[f] = i; box.appendChild(i);
  });
  const ok = document.createElement("button"); ok.textContent = "확인";
  ok.onclick = () => {
    const qs = new URLSearchParams({ thread_id: threadId });
    fields.forEach((f) => { if (inputs[f].value) qs.set(f, inputs[f].value); });
    wrap.innerHTML = ""; setBusy(true);
    openStream("/diagnose/resume?" + qs.toString());
  };
  const rej = document.createElement("button"); rej.textContent = "중단"; rej.className = "rej";
  rej.onclick = () => {
    wrap.innerHTML = ""; setBusy(true);
    openStream("/diagnose/resume?" + new URLSearchParams({ thread_id: threadId, reject: "true" }).toString());
  };
  box.appendChild(ok); box.appendChild(rej);
  wrap.appendChild(box);
}

// ── 카카오맵: JS키는 /config(.env)서 받아 SDK 동적 로드. 도메인 미등록/키없음이면 graceful 생략 ──
async function loadKakao() {
  try {
    const r = await fetch("/config");
    const j = await r.json();
    if (!j.kakao_js_key) return;
    const s = document.createElement("script");
    s.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${j.kakao_js_key}&autoload=false`;
    s.onload = () => { if (window.kakao && kakao.maps) kakao.maps.load(() => { window._kakaoReady = true; }); };
    s.onerror = () => console.warn("kakao SDK 로드 실패 — 카카오 콘솔에 localhost:8000 도메인 등록 확인");
    document.head.appendChild(s);
  } catch (e) { /* config 없으면 맵 생략 */ }
}

function renderMap(xy, address, jimok, zone) {
  const el = document.getElementById("map");
  if (!el) return;
  if (!xy || !window._kakaoReady || !window.kakao || !kakao.maps) { el.style.display = "none"; return; }
  el.style.display = "block";
  const center = new kakao.maps.LatLng(xy[1], xy[0]);   // VWorld x=경도, y=위도 → LatLng(위도, 경도)
  const map = new kakao.maps.Map(el, { center, level: 3 });
  new kakao.maps.Marker({ position: center, map });
  new kakao.maps.InfoWindow({
    position: center,
    content: `<div style="padding:5px 9px;font-size:12px;white-space:nowrap">${address || ""} · 지목 ${jimok || "?"} · ${zone || "?"}</div>`,
  }).open(map);
}

loadKakao();
$("#in").addEventListener("submit", start);
