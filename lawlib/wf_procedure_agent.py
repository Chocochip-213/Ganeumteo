# -*- coding: utf-8 -*-
"""절차 프레임 = agent-loop 라우팅 인덱스. AGENT_SYSTEM 절차 산문 단계를 코드 시드로.
PROC_FRAME = 표준 건축행정절차 단계 → (어느 법 어느 조가 그 단계를 규율하나)만.
효과·적용여부·순서 verdict 하드코딩 0 — applies/순서/면제는 전부 LLM이 fetch 원문으로 판정.
REG_SEED(wf_reg_agent.py:29-40)와 같은 철학: 검색 시작점일 뿐 판정 근거 아님."""

# 단계 = (step_id, order, stage_key, law, articles, gate_hint, is_doc_stage)
#  - order: 표준 건축행정절차의 '시간축 슬롯'(코드가 정한 케이스 순서 아님 — 표준틀의 자리).
#           케이스별 순서·생략은 LLM이 applies로. 허가/신고/용도변경은 같은 슬롯에 병치해 코드가 택일 안 함.
#  - articles: '이 단계를 어디서 읽나' 후보(복수 가능 — REG_SEED.articles처럼). 코드는 효과를 안 읽음.
#  - gate_hint: 이 단계가 '조건부'임을 LLM에 환기(조건만 — 결론어 금지). applies 판정은 LLM이 원문으로.
#  - is_doc_stage: docs_for_stage가 첨부서류를 가져올 수 있는 실제 인허가 단계인가(절차↔서류 연결고리 표시).
PROC_FRAME = [
 {"step_id": "사전결정",   "order": 1,  "stage_key": "사전결정",     "law": "건축법", "articles": ["10"],
  "gate_hint": "건축허가 대상 건축물, 허가 전 임의신청(신청 의사 있을 때 — §10⑥ 의제 결합)", "is_doc_stage": False},
 {"step_id": "건축심의",   "order": 2,  "stage_key": "건축위원회심의", "law": "건축법", "articles": ["4의2"],
  "gate_hint": "다중이용건축물·특수구조·일정규모 등 시행령·조례 대상 여부를 원문으로 확인", "is_doc_stage": False},
 {"step_id": "건축허가",   "order": 3,  "stage_key": "건축허가",     "law": "건축법", "articles": ["11"],
  "gate_hint": "원칙 허가대상. §11⑤ 관계 인허가 의제 결합 지점 — record_uijae 의제를 여기에 when_note로 묶어라", "is_doc_stage": True},
 {"step_id": "건축신고",   "order": 3,  "stage_key": "건축신고",     "law": "건축법", "articles": ["14"],
  "gate_hint": "소규모는 허가 갈음 신고(§14 면적·층수 한계를 원문으로 판정). 허가/신고는 work_type따라 택일", "is_doc_stage": True},
 {"step_id": "용도변경",   "order": 3,  "stage_key": "용도변경",     "law": "건축법", "articles": ["19"],
  "gate_hint": "기존 건물 용도변경일 때(§19 시설군 상호변경). 신축 아니면 허가 단계 대신 이 단계", "is_doc_stage": True},
 {"step_id": "대수선",     "order": 3,  "stage_key": "대수선",       "law": "건축법", "articles": ["11", "14"],
  "gate_hint": "대수선일 때(규모따라 허가/신고를 §11·§14 원문으로 구분)", "is_doc_stage": True},
 {"step_id": "해체",       "order": 4,  "stage_key": "해체",         "law": "건축물관리법", "articles": ["30"],
  "gate_hint": "기존 건축물 철거 동반 여부를 케이스 사실로 확인. 규모따라 허가/신고(§30 원문)", "is_doc_stage": True},
 {"step_id": "착공신고",   "order": 5,  "stage_key": "착공신고",     "law": "건축법", "articles": ["21"],
  "gate_hint": "허가/신고 후 공사 착수 전", "is_doc_stage": True},
 {"step_id": "감리보고",   "order": 6,  "stage_key": "감리보고",     "law": "건축법", "articles": ["25"],
  "gate_hint": "시행령 대상 용도·규모 여부 확인. 중간·완료보고(시행령 §19 공정단계)", "is_doc_stage": False},
 {"step_id": "사용승인",   "order": 7,  "stage_key": "사용승인",     "law": "건축법", "articles": ["22"],
  "gate_hint": "공사 완료 후 사용 전 필수. 감리완료보고서 첨부", "is_doc_stage": True},
 {"step_id": "대장등재",   "order": 8,  "stage_key": "건축물대장등재", "law": "건축법", "articles": ["38"],
  "gate_hint": "사용승인 시 처분청 직권 기재(사용승인 후 단계)", "is_doc_stage": False},
 {"step_id": "유지관리",   "order": 9,  "stage_key": "유지관리",     "law": "건축물관리법", "articles": ["12", "13"],
  "gate_hint": "사용승인 후 관리자 의무(§12 일반 유지관리 · §13 정기점검 — 대상 건축물 여부 확인)", "is_doc_stage": False},
]


def frame():
    """표준 건축행정절차 프레임 전체 반환 — '검토 대상 단계 + 어느 법조서 읽나'.
    적용여부·순서·허가신고택일·면제는 전혀 결정 안 함(LLM이 fetch 원문으로). REG_SEED.resolve와 동형:
    코드는 라우팅 포인터만, status 없음(절차의 applies/status는 ProcedureStep이 들고 record 도구가 검증)."""
    return [dict(f) for f in PROC_FRAME]
