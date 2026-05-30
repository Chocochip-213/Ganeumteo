# -*- coding: utf-8 -*-
"""GaneomteoState + Pydantic 타입. 명세 §3.2/§3.1 정규 필드(D0.3)."""
from typing import Annotated, Optional, List, Literal
from typing_extensions import TypedDict, NotRequired
import operator
from pydantic import BaseModel, Field
from langgraph.graph.message import add_messages


class Citation(BaseModel):
    source: str                       # vworld | law | ordin | data
    law_name: Optional[str] = None
    article: Optional[str] = None     # 조/별표
    title: Optional[str] = None
    quote: str = ""                   # 원문 인용 ≤200
    url: Optional[str] = None
    extract_method: Optional[str] = None   # 조례 청크 출처: 인덱스청크|BodyText|PrvText(캡)|hwpx (가늠터 UI)


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


class RegEffect(BaseModel):
    reg_name: str
    law_name: Optional[str] = None
    article: Optional[str] = None
    effect: str = ""


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
    act_verdict: NotRequired[str]
    act_reg_raw: NotRequired[list]
    _delegated: NotRequired[bool]
    doc_index_hit: NotRequired[bool]   # 조례 RAG 인덱스 HIT 여부(가늠터 UI 트레이스 노출)
    verdict: NotRequired[str]
    # ── 산출 (누적=operator.add)
    uijae: Annotated[list, operator.add]
    documents: Annotated[list, operator.add]
    cond_assessments: Annotated[list, operator.add]   # 조건부('해당시만') 서류 케이스 판정 — 에이전트가 상태/사용자질의로 결정({stage_key,ho,applies,reason})
    reg_effects: Annotated[list, operator.add]
    jorye_verdicts: Annotated[list, operator.add]
    author: NotRequired[dict]
    term_notes: NotRequired[dict]            # 진단맥락 용어설명(에이전트가 state 사실로 생성) — 프론트 popover(when_note 패턴)
    scale_limits: NotRequired[dict]          # compute_scale·compute_envelope 공용(overwrite — envelope가 ScaleLimit 확장)
    parking_req: NotRequired[dict]           # parking_quota 산출(부설주차 N대) — scale_limits와 분리(덮어쓰기 충돌 방지)
    levies: Annotated[list, operator.add]    # 부담금(농지보전·대체산림·개발) — levy_estimate가 누적
    citations: Annotated[list, operator.add]
    abstentions: Annotated[list, operator.add]
    legal_reasoning: NotRequired[dict]
    # ── 제어
    _toolcalls: Annotated[list, operator.add]        # 호출한 도구명 누적 (완결성 가드용)
    _steps: Annotated[int, operator.add]             # agent 방문 횟수 (루프 하드캡)
    _turn_base_steps: NotRequired[int]               # 이번 invoke 시작 시 _steps — 후속턴 per-invoke 하드캡 기준(thread 누적 아님)
    _turn_base_tools: NotRequired[int]               # 이번 invoke 시작 시 len(_toolcalls) — 후속턴 chat_end 판정 기준
    _incomplete: NotRequired[bool]
    terminal_reason: NotRequired[str]
    _card: NotRequired[dict]
    _return: NotRequired[dict]               # 부록 D2 ReturnEnvelope(status+card+abstentions)
