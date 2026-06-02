# -*- coding: utf-8 -*-
"""GaneomteoState + Pydantic 타입. 명세 §3.2/§3.1 정규 필드(D0.3)."""
from typing import Annotated, Optional, List, Literal
from typing_extensions import TypedDict, NotRequired
import operator
from pydantic import BaseModel, Field
from langgraph.graph.message import add_messages


def _merge_facts(a, b):   # document_facts 누적 병합(여러 HITL 라운드 답을 합침)
    return {**(a or {}), **(b or {})}


def _reject_reducer(old, new):   # record 도구 거부 카운터 — 거부=+1 누적, 성공커밋=0 리셋(연속거부만 추적)
    return 0 if new == 0 else (old or 0) + new


# ── 근거계약 공통 토대 (MASTER_PLAN item 0) ─────────────────────────────
# 0a. 공통 UnresolvedBy enum — 미해결 분류 단일 정의(전 모델 동일). unknown→none 조용한 강등 금지.
_UNRESOLVED = Literal["none", "agent", "user", "authority", "data_unavailable", "tool_budget_exhausted"]
_UNRESOLVED_VALUES = ("none", "agent", "user", "authority", "data_unavailable", "tool_budget_exhausted")
# 최종 카드 잔존 허용 미해결(agent=완료금지·루프백 — §0 규칙 2b)
_RESOLVED_TERMINAL = ("user", "authority", "data_unavailable", "tool_budget_exhausted")
_CLAIM_TYPES = ("factual_input", "legal_applicability", "calculation_basis", "authority_discretion")


def _evidence_kind(eid):
    """evidence_id 접두 → 종류(law/ordin/api/user_fact/doc_fact/static). 코드는 종류만 읽음(의미 아님)."""
    return (str(eid).split(":", 1)[0] or "").strip()


def _claim_kind_ok(claim_type, eid):
    """claim_type × evidence-kind 허용룰(0b) — 관계만 검증, 논리지지는 LLM 책임.
    user_fact→factual_input만(법결론 근거 불가) · static→calculation_basis만 · law/ordin/api/doc_fact→전 타입."""
    kind = _evidence_kind(eid)
    if kind == "user_fact":
        return claim_type == "factual_input"
    if kind == "static":
        return claim_type == "calculation_basis"
    return claim_type in _CLAIM_TYPES


def _merge_steps(a, b):   # procedure_steps: step_id 기준 last-write-wins(ReAct 재기록 stale 누적 방지)
    out = {x.get("step_id"): x for x in (a or []) if isinstance(x, dict) and x.get("step_id")}
    for x in (b or []):
        if isinstance(x, dict) and x.get("step_id"):
            out[x["step_id"]] = {**out.get(x["step_id"], {}), **x}
    return list(out.values())


def _merge_evidence(a, b):   # evidence_records: evidence_id 키 dict union(b=최신 우선)
    return {**(a or {}), **(b or {})}


class Citation(BaseModel):
    source: str                       # vworld | law | ordin | data
    law_name: Optional[str] = None
    article: Optional[str] = None     # 조/별표
    title: Optional[str] = None
    quote: str = ""                   # 원문 인용 ≤200
    url: Optional[str] = None
    extract_method: Optional[str] = None   # 조례 청크 출처: 인덱스청크|BodyText|PrvText(캡)|hwpx (가늠터 UI)
    source_id: Optional[str] = None        # 근거 식별자(law_name|article) — record_ordinance_ruling relied_source_ids 매칭(U5)
    truncated: bool = False                # 본문이 표시 캡에서 잘렸나(잘린 근거 위 단정 금지 — build_reasoning truncated_basis 게이트)
    read_coverage: Optional[float] = None  # 표시/전체 비율(0~1) — 진단·표시용, 게이트 임계로는 안 씀


class UijaeItem(BaseModel):
    trigger: str
    permit_name: str
    stage_key: str
    citation: Optional[Citation] = None   # 부록 D 수정: 의제 근거


class DocItem(BaseModel):
    ho: str
    doc_name: str
    has_proviso: bool = False
    conditional: bool = False          # 해당시만 제출(법 "~경우로 한정" 등)
    item_type: str = "doc"             # doc(제출서류) | group(각 목 헤더) | spec(서류 세부명세) | cross_ref(관계법령 위임=의제서류로 해소)
    form_title: str = ""               # 이 호가 별지서식 참조시 양식명
    form_hwp: str = ""                 # 양식 HWP 다운로드 URL
    form_pdf: str = ""                 # 양식 PDF 다운로드 URL


class StageDocs(BaseModel):
    stage_key: str
    law: str = ""
    article: str = ""
    when_note: str = ""                # 이 단계를 '언제' 하는지(에이전트가 건축법 절차 근거로 생성한 한 줄)
    when_law: str = ""                 # 시점·의미 근거 본법 조(예 '건축법 제21조')
    when_title: str = ""               # 본법 조문제목(=단계 의미)
    when_quote: str = ""               # 본법 조문 원문(hover 인용)
    author_note: str = ""              # 이 단계 작성주체(에이전트가 법령근거로 생성: 신청인/건축사§23/감리자§25)
    status: str = "전수확보"
    count: int = 0
    apply_title: str = ""              # 주신청서 양식명
    apply_hwp: str = ""                # 주신청서 HWP 다운로드 URL
    apply_pdf: str = ""                # 주신청서 PDF 다운로드 URL
    items: List[DocItem] = Field(default_factory=list)


class JoryeVerdict(BaseModel):
    ordin_name: Optional[str] = None
    byeolpyo: Optional[str] = None
    verdict: Literal["가능", "불가", "확인필요"] = "확인필요"
    reason: Optional[str] = None
    relied_source_ids: List[str] = Field(default_factory=list)   # 이 판정이 의존한 근거 source_id들 — 잘린 근거 의존 단정을 build_reasoning이 강등(U5)


class VerdictLabel(BaseModel):
    dimension: str                                    # 판정 축 이름 — LLM이 케이스마다 정함(코드 고정목록 아님)
    status: Literal["충족", "주의", "확인필요", "불가"] = "주의"   # 축 판정(표시·일관성 가드 어휘)
    reason: str = ""                                  # 평이한 한 줄 사유
    basis_seq: List[int] = Field(default_factory=list)   # 근거 citation/step seq
    blocking_level: Literal["none", "critical"] = "none"   # 이 축이 핵심(미충족이면 진행 불가)인지 — LLM-set, record_verdict 게이트가 읽음
    unresolved_by: _UNRESOLVED = "none"   # 미해소면 누가 푸나(공통 0a enum) — LLM-set. agent=더조사(완료금지)·authority=관할심의·user=사실확인·data_unavailable=데이터부재·tool_budget_exhausted=캡소진
    basis_claims: List[dict] = Field(default_factory=list)   # item 11: 근거계약 BasisClaim들(evidence_id 실재 검증) — basis_seq는 표시용 잔존


class RegEffect(BaseModel):
    reg_name: str
    law_name: Optional[str] = None
    article: Optional[str] = None
    effect: str = ""
    status: str = "근거확보"   # 근거확보|확인필요(reg_effect_resolve_tool fetch=자료확보, 결론 아님) · 해소|미해소|해당없음(record_reg_resolution LLM 판정) — 미해결도 카드서 안 사라지게 보존
    resolution_committed: bool = False   # LLM이 record_reg_resolution로 영향판정 커밋했나(item 1) — fetch=False, LLM판정=True. 근거확보≠완료를 코드가 분별(완료게이트가 읽음)
    blocking_level: str = "normal"   # LLM이 record_reg_resolution로 세팅: critical|normal|reference(코드는 읽기만 — 어느 규제가 critical인지 코드가 안 정함)
    unresolved_by: _UNRESOLVED = "none"   # status=확인필요면 누가 푸나(공통 0a enum) — bare 확인필요 금지
    basis_seq: List[int] = Field(default_factory=list)   # record_reg_resolution 근거 citation/step seq(표시용 잔존)
    basis_claims: List[dict] = Field(default_factory=list)   # 결론성 status 근거계약(BasisClaim들·evidence_id 실재 검증, item 1)


class AuthorRule(BaseModel):
    requires_architect: bool
    reason: str = ""


class ScaleLimit(BaseModel):
    energy_saving_required: bool
    structural_safety_required: bool
    notes: List[str] = Field(default_factory=list)
    # 건폐율·용적률 envelope(compute_envelope가 채움 — bcr/far는 LLM이 시행령§84/§85·조례서 읽어 전달)
    max_building_area: Optional[float] = None   # 대지면적×건폐율% (㎡)
    max_floor_area: Optional[float] = None      # 대지면적×용적률% (㎡)
    approx_floors: Optional[float] = None        # 연면적/건축면적 약식층수
    envelope_note: Optional[str] = None          # 근거·확인필요 꼬리표(용적률 범위함정 등)


class LevyItem(BaseModel):
    """부담금: 산식은 법공식(결정적), 단가·금액은 LLM이 법령서 읽은 값만. 없으면 amount=None+확인필요."""
    levy_type: str                                # 농지보전부담금 | 대체산림자원조성비 | 개발부담금
    formula: str = ""                             # 산식(법 공식)
    amount: Optional[int] = None                  # 산출 금액(원). 단가 데이터원 없으면 None
    status: str = "확인필요"                       # 산출 | 확인필요
    note: str = ""
    citation: Optional[Citation] = None


# 0b. BasisClaim — 근거ID 존재만으론 부족(ID-washing). 어느 결론필드를 어떤 claim_type으로 지지하는지 결속.
class BasisClaim(BaseModel):
    field_path: str = ""        # 어느 결론필드 지지(예 'VerdictLabel.final_verdict'·'ProcedureStep.applies') — LLM-set, 코드 의미판단 X
    decision_key: str = ""
    claim_type: Literal["factual_input", "legal_applicability", "calculation_basis", "authority_discretion"] = "factual_input"
    evidence_id: str
    support_role: Literal["supports", "refutes", "context"] = "supports"
    quote_or_span: str = ""     # 원문 인용/스팬 — EvidenceRecord.raw에 실재해야(위조 차단)


# 0b-2. EvidenceRecord — 원문 store(quote 실재검증 토대). 표시 quote(Citation.quote)와 별개.
class EvidenceRecord(BaseModel):
    evidence_id: str            # 안정·결정적 키(예 'law:건축법 시행령|별표1'·'api:act_landuse|<hash>')
    source: str = ""            # law | ordin | api | user_fact | doc_fact
    raw_text: str = ""          # fetch 원문(quote ∈ raw 대조용)
    source_url: Optional[str] = None
    law_id: Optional[str] = None     # 법령일련번호/MST
    effective_date: Optional[str] = None
    content_hash: Optional[str] = None
    truncated: bool = False
    read_coverage: Optional[float] = None
    fetched_at: Optional[str] = None


# 0b-2. StaticEvidenceRecord — 법정 결정상수 전용(fetch raw 아님). static_evidence는 calculation_basis claim에만.
class StaticEvidenceRecord(BaseModel):
    const_id: str
    value: float
    source_evidence_id: Optional[str] = None
    effective_date: Optional[str] = None
    last_verified_at: Optional[str] = None


# 0d. WorkTypeResolution — 신축/용도변경/대수선/증축/해체 구조화 커밋(맹지·절차 게이트가 읽는 단일원).
class WorkTypeResolution(BaseModel):
    work_type: Literal["신축", "용도변경", "대수선", "증축", "해체", "확인필요"] = "확인필요"
    status: Literal["확정", "확인필요"] = "확인필요"
    unresolved_by: _UNRESOLVED = "none"
    basis_claims: List[dict] = Field(default_factory=list)


# item 4. UseClassification — 생활어→건축법 시행령 별표1 canonical use 선행 확정(act_landuse 선결).
class UseClassification(BaseModel):
    original_use: str = ""      # 사용자 생활어(카페·피시방·사무소)
    canonical_use: str = ""     # 별표1 세목(휴게음식점·인터넷컴퓨터게임시설제공업소·업무시설)
    law_basis: str = ""
    basis_claims: List[dict] = Field(default_factory=list)
    status: Literal["확정", "확인필요"] = "확인필요"
    unresolved_by: _UNRESOLVED = "none"


# item 3. LanduseResolution — 행위제한 API raw 위에 LLM이 NODE_DESC↔intended_use 일치 확인 후 긍정 커밋(코드 act_verdict 대체).
class LanduseResolution(BaseModel):
    intended_use: str = ""
    matched_node_desc: str = ""
    api_reg_nm: str = ""
    status: Literal["가능", "불가", "조건필요", "확인필요"] = "확인필요"
    unresolved_by: _UNRESOLVED = "none"
    basis_claims: List[dict] = Field(default_factory=list)
    mismatch_reason: str = ""


# item 10. ProcedureStep — 인허가 절차 타임라인(documents와 분리). field 단위 basis(0e). verdict/blocking_level 미포함.
class ProcedureStep(BaseModel):
    step_id: str
    order: float = 0
    stage_key: str = ""
    phase: str = ""
    title: str = ""
    applies: Literal["yes", "no", "unknown"] = "yes"
    status: Literal["근거확보", "확인필요"] = "확인필요"
    unresolved_by: _UNRESOLVED = "none"
    actor: str = ""
    authority: str = ""
    trigger: str = ""
    action: str = ""
    when_note: str = ""
    deadline: str = ""
    law_name: str = ""
    article: str = ""
    title_from_law: str = ""
    quote: str = ""
    basis_claims: List[dict] = Field(default_factory=list)   # field 단위(field_path=ProcedureStep.applies/.status/.when/.authority/.action)
    citation_ids: List[str] = Field(default_factory=list)
    related_document_stage_keys: List[str] = Field(default_factory=list)
    requires_documents: bool = False
    source_api: str = ""
    notes: List[str] = Field(default_factory=list)


def collect_evidence_ids(state):
    """state에 실재하는 evidence_id 합집합(근거계약 검증 대상). 코드=운반·집계(의미 아님).
    citations.source_id ∪ EvidenceRecord 키 ∪ user_fact:<k> ∪ doc_fact:<k>(document_facts)."""
    ids = set()
    for c in (state.get("citations") or []):
        sid = c.get("source_id") if isinstance(c, dict) else None
        if sid:
            ids.add(sid)
    for k in (state.get("evidence_records") or {}):
        if k:
            ids.add(k)
    for k in (state.get("document_facts") or {}):
        if k:
            ids.add(f"user_fact:{k}"); ids.add(f"doc_fact:{k}")
    return ids


def validate_basis_claims(state, basis_claims, *, require_quote=True):
    """근거계약 검증(MASTER_PLAN 0c) — 구조만, 의미판단 X.
    각 claim: evidence_id ∈ collect_evidence_ids + claim_type×evidence-kind 허용 + (raw 보유시) quote ∈ raw.
    논리지지(이 근거가 정말 이 결론을 받치나)는 LLM/record 도구 책임. 반환 (ok, errors=[(idx,사유)])."""
    ids = collect_evidence_ids(state)
    recs = state.get("evidence_records") or {}
    errors = []
    for i, cl in enumerate(basis_claims or []):
        c = cl if isinstance(cl, dict) else (cl.model_dump() if hasattr(cl, "model_dump") else {})
        eid = c.get("evidence_id")
        if not eid:
            errors.append((i, "evidence_id 비어있음")); continue
        if eid not in ids:
            errors.append((i, f"evidence_id 미실재:{eid}")); continue
        ct = c.get("claim_type", "factual_input")
        if not _claim_kind_ok(ct, eid):
            errors.append((i, f"claim_type×evidence-kind 위반:{ct}↔{_evidence_kind(eid)}")); continue
        if require_quote:
            q = (c.get("quote_or_span") or "").strip()
            rec = recs.get(eid)
            raw = (rec.get("raw_text") if isinstance(rec, dict) else "") or ""
            if q and raw and q not in raw:   # raw 보유 evidence만 quote 실재 대조(user_fact/doc_fact는 raw 없어 면제)
                errors.append((i, f"quote 원문 미실재:{eid}"))
    return (not errors, errors)


class GaneomteoState(TypedDict):
    messages: Annotated[list, add_messages]          # ReAct 루프 (LangGraph)
    # ── 입력
    address: str
    use_type: str
    floor_area: float
    floor_count: int
    work_type: NotRequired[str]
    # ── 입지 (도구가 Command(update)로 충전 — 부록 G2.1)
    _xy: NotRequired[list]
    pnu: NotRequired[str]
    area_cd: NotRequired[str]
    sigungu: NotRequired[str]
    jimok: NotRequired[str]
    zone: NotRequired[str]
    zone_ucodes: NotRequired[list]
    road_side: NotRequired[str]
    land_price: NotRequired[Optional[int]]
    land_area: NotRequired[Optional[float]]   # 대지면적 lndpclAr(㎡) — get_land_use가 추출, 부담금·envelope 입력
    reg_overlaps: Annotated[list, operator.add]
    # ── 판정
    act_landuse_raw: NotRequired[str]   # act_landuse 원시 신호(REG_NM·NODE_DESC detail) — 표시/probe만, verdict 입력 아님(item 3 rename·재오염 방지)
    act_reg_raw: NotRequired[list]
    _delegated: NotRequired[bool]
    doc_index_hit: NotRequired[bool]   # 조례 RAG 인덱스 HIT 여부(가늠터 UI 트레이스 노출)
    verdict: NotRequired[str]
    _llm_verdict: NotRequired[str]                     # record_verdict가 LLM 합성으로 커밋한 최종판정(build_reasoning이 _derive_verdict 대신 사용; 없으면 fallback)
    document_facts: Annotated[dict, _merge_facts]      # 사용자가 확인해준 서류판단 사실(권원·공동소유·사전결정·분할납부 등) — request_human_input이 durable 저장, 카드 노출
    # ── 산출 (누적=operator.add)
    uijae: Annotated[list, operator.add]
    documents: Annotated[list, operator.add]
    cond_assessments: Annotated[list, operator.add]   # 조건부('해당시만') 서류 케이스 판정 — 에이전트가 상태/사용자질의로 결정({stage_key,ho,applies,reason})
    reg_effects: Annotated[list, operator.add]
    jorye_verdicts: Annotated[list, operator.add]
    verdict_labels: Annotated[list, operator.add]     # record_verdict 다차원 판정 축(축 이름·개수는 LLM이 케이스마다 정함 — 코드 고정목록 없음)
    _verdict_round: NotRequired[list]                 # 최신 record_verdict 라운드 라벨만(last-write-wins) — 카드는 이걸 써 다라운드 stale 축 제거(U3)
    # ── 근거계약·신규 산출 (MASTER_PLAN item 0 토대; append-only/merge, latest selector로 읽음 — 0g)
    evidence_records: Annotated[dict, _merge_evidence]     # evidence_id → EvidenceRecord(원문 store, quote 실재검증 토대 0b-2)
    procedure_steps: Annotated[list, _merge_steps]        # 인허가 절차 타임라인(record_procedure_steps) — documents와 분리(item 10)
    landuse_resolutions: Annotated[list, operator.add]    # record_landuse_resolution(행위제한 LLM 판정) — 코드 act_verdict 긍정 대체(item 3)
    use_classifications: Annotated[list, operator.add]    # record_use_classification(생활어→canonical use 별표1, item 4)
    work_type_resolutions: Annotated[list, operator.add]  # record_work_type(WorkTypeResolution 구조화) — 맹지/절차 게이트가 읽는 단일원(item 9·0d)
    author: NotRequired[dict]
    term_notes: NotRequired[dict]            # 진단맥락 용어설명(에이전트가 state 사실로 생성) — 프론트 popover(when_note 패턴)
    scale_limits: NotRequired[dict]          # compute_scale 전용(에너지/구조안전 — 실 연면적 기준)
    envelope: NotRequired[dict]              # compute_envelope 전용(건폐율·용적률 최대치) — scale_limits와 분리(병렬 동시쓰기 충돌 방지)
    parking_req: NotRequired[dict]           # parking_quota 산출(부설주차 N대) — scale_limits와 분리(덮어쓰기 충돌 방지)
    levies: Annotated[list, operator.add]    # 부담금(농지보전·대체산림·개발) — levy_estimate가 누적
    citations: Annotated[list, operator.add]
    abstentions: Annotated[list, operator.add]
    legal_reasoning: NotRequired[dict]
    # ── 제어
    _toolcalls: Annotated[list, operator.add]        # 호출한 도구명 누적 (완결성 가드용)
    _steps: Annotated[int, operator.add]             # agent 방문 횟수 (루프 하드캡)
    _reject_count: Annotated[int, _reject_reducer]   # record_* 연속 거부 횟수(doom-loop 조기차단) — 거부+1·성공커밋0
    _turn_base_steps: NotRequired[int]               # 이번 invoke 시작 시 _steps — 후속턴 per-invoke 하드캡 기준(thread 누적 아님)
    _turn_base_tools: NotRequired[int]               # 이번 invoke 시작 시 len(_toolcalls) — 후속턴 chat_end 판정 기준
    _incomplete: NotRequired[bool]
    terminal_reason: NotRequired[str]
    _card: NotRequired[dict]
    _return: NotRequired[dict]               # 부록 D2 ReturnEnvelope(status+card+abstentions)
