# -*- coding: utf-8 -*-
"""GaneomteoState + Pydantic 타입. 명세 §3.2/§3.1 정규 필드(D0.3)."""
from typing import Annotated, Optional, List
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


class UijaeItem(BaseModel):
    trigger: str
    permit_name: str
    stage_key: str
    citation: Optional[Citation] = None   # 부록 D 수정: 의제 근거


class DocItem(BaseModel):
    ho: str
    doc_name: str
    has_proviso: bool = False


class StageDocs(BaseModel):
    stage_key: str
    law: str = ""
    article: str = ""
    status: str = "전수확보"
    count: int = 0
    items: List[DocItem] = Field(default_factory=list)


class JoryeVerdict(BaseModel):
    ordin_name: Optional[str] = None
    byeolpyo: Optional[str] = None
    verdict: str = "확인필요"
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
    reg_overlaps: Annotated[list, operator.add]
    # ── 판정
    act_verdict: NotRequired[str]
    act_reg_raw: NotRequired[list]
    _delegated: NotRequired[bool]
    verdict: NotRequired[str]
    # ── 산출 (누적=operator.add)
    uijae: Annotated[list, operator.add]
    documents: Annotated[list, operator.add]
    reg_effects: Annotated[list, operator.add]
    jorye_verdicts: Annotated[list, operator.add]
    author: NotRequired[dict]
    scale_limits: NotRequired[dict]
    citations: Annotated[list, operator.add]
    abstentions: Annotated[list, operator.add]
    legal_reasoning: NotRequired[dict]
    # ── 제어
    _toolcalls: Annotated[list, operator.add]        # 호출한 도구명 누적 (완결성 가드용)
    _steps: Annotated[int, operator.add]             # agent 방문 횟수 (루프 하드캡)
    _incomplete: NotRequired[bool]
    terminal_reason: NotRequired[str]
    _card: NotRequired[dict]
    _return: NotRequired[dict]               # 부록 D2 ReturnEnvelope(status+card+abstentions)
