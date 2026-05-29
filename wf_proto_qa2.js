export const meta = {
  name: 'ganeomteo-proto-qa2',
  description: '가늠터 ReAct 프로토타입 대규모 QA — 스펙적합·LangGraph정확성·툴명세·claude src패턴·인허가 도메인정확성·멀티실행·엣지·일관성 17병렬 → 종합',
  phases: [
    { title: '검증', detail: '17 에이전트 병렬: 코드/스펙/LangGraph/claude패턴/도메인/실행/엣지/일관성' },
    { title: '종합', detail: '품질 리포트 + 우선순위 수정 + implement-ready 판정' },
  ],
}

const P = 'C:\\Users\\kmw16\\Desktop\\agent\\probe\\react_proto'
const R = 'C:\\Users\\kmw16\\Desktop\\agent\\probe\\research'
const SPEC = R + '\\GANEOMTEO_IMPL_SPEC.md'
const CC = 'C:\\Users\\kmw16\\Desktop\\claude\\src\\agentic_study_output\\CLAUDE_CODE_ANALYSIS_COMPILED.md'
const CSRC = 'C:\\Users\\kmw16\\Desktop\\claude\\src'

const FIND = {
  type: 'object',
  properties: {
    dimension: { type: 'string' },
    verdict: { type: 'string' },
    findings: { type: 'array', items: { type: 'object', properties: {
      severity: { type: 'string' }, loc: { type: 'string' }, problem: { type: 'string' }, fix: { type: 'string' }
    }, required: ['severity', 'problem', 'fix'] } },
    strengths: { type: 'array', items: { type: 'string' } },
    evidence: { type: 'array', items: { type: 'string' } },
  },
  required: ['dimension', 'verdict', 'findings'],
}

phase('검증')
const PROTO_FILES = P + '\\state.py, ' + P + '\\tools.py, ' + P + '\\agent.py, ' + P + '\\graph.py, ' + P + '\\run.py, ' + P + '\\trace.py'

const DIMS = [
  { key: 'langgraph', label: '검증:LangGraph정확성', prompt:
'LangGraph API를 프로토타입이 정확히 썼는지 적대 검수. Read: ' + PROTO_FILES + '.\n' +
'점검: StateGraph·add_node·add_conditional_edges·ToolNode·@tool·InjectedToolCallId·Command(update)·add_messages 리듀서·operator.add·checkpointer(MemorySaver)+thread_id·interrupt·graph.stream(stream_mode). 컴파일/실행 가능한가, 잘못된 시그니처/리듀서/엣지 있나, recursion_limit·루프가드 정합한가.\n' +
'필요하면 ' + CSRC + ' 의 실제 구현이나 LangGraph 패턴 참고. findings(severity high/med/low·loc·problem·fix)·strengths·evidence(파일:라인). 빡세게.' },
  { key: 'spec_arch', label: '검증:스펙-아키텍처', prompt:
'프로토타입 그래프가 명세 부록 G(ReAct 7노드)대로인지 검수. Read 명세 ' + SPEC + '(Grep 부록 G·G1·G5) + ' + P + '\\graph.py.\n' +
'점검: agent⇄tools 루프·completeness_guard·build_reasoning·compose·finalize·abstain 노드와 엣지가 G1과 일치하나. 누락 노드/엣지/라우터, 명세와 다른 흐름. findings·strengths·evidence.' },
  { key: 'spec_tools', label: '검증:툴명세', prompt:
'도구 구현이 명세 §4 Tool카탈로그·부록 G2/G2.1과 일치하는지 검수. Read 명세 ' + SPEC + '(Grep §4·G2·G2.1) + ' + P + '\\tools.py.\n' +
'점검: 각 도구(geocode/get_parcel/get_land_use/get_land_price/act_landuse/ordin_byeolpyo_fetch/law_byeolpyo_fetch/docs_for_stage/compute_scale/author_rule_tool/reg_effect_resolve_tool/record_uijae/record_ordinance_ruling/request_human_input)의 시그니처·반환(Command update)·State 충전 필드·citation·ToolMessage가 명세와 일치하나. 누락 도구, 잘못된 반환, 명세 미반영. findings·strengths·evidence.' },
  { key: 'spec_state', label: '검증:State스키마', prompt:
'State 스키마가 명세 §3.2/D0.3 정규 필드와 일치하는지 검수. Read 명세 ' + SPEC + '(Grep §3.2·D0.3·GaneomteoState) + ' + P + '\\state.py.\n' +
'점검: 필드명(정규)·타입·리듀서(operator.add vs overwrite)·Pydantic 타입(Citation/UijaeItem/StageDocs/JoryeVerdict/RegEffect/AuthorRule/ScaleLimit). 명세 정규명과 드리프트, 누락 필드. findings·strengths·evidence.' },
  { key: 'spec_guard', label: '검증:가드/종료계약', prompt:
'환각가드·citation·종료계약이 명세 §9/§11/부록 D2/E대로인지 검수. Read 명세 ' + SPEC + '(Grep 부록 D2·E·§9 환각가드) + ' + P + '\\graph.py + ' + P + '\\tools.py.\n' +
'점검: ①사실=tool fetch ②build_reasoning 단계 basis ③verdict 강등(핵심단계 근거없음) ④citations 0→abstain ⑤terminal_reason 7값·보존·finalize. 명세 대비 누락/약화. findings·strengths·evidence.' },
  { key: 'spec_rag', label: '검증:조례RAG/멀티홉', prompt:
'조례 RAG·멀티홉이 명세 부록 G2.1b/G5·§5·§6대로인지 검수. Read 명세 ' + SPEC + '(Grep 조례 RAG·멀티홉·BodyText·G5) + ' + P + '\\tools.py(ordin_byeolpyo_fetch/law_byeolpyo_fetch/_ordin_bodytext).\n' +
'점검: 조례 별표 HWP→BodyText(zlib) 추출·별표 제목/번호 매칭·멀티홉(조례별표→건축법령 별표1 호목)·운영(사전인덱싱)vs실증(런타임) 구분. findings·strengths·evidence.' },
  { key: 'cc_loop', label: '검증:claude루프패턴', prompt:
'가늠터 Agent Loop가 claudecode 에이전트 철학을 따르는지 대조. Read ' + CC + '(Grep 에이전트 루프·queryLoop·Terminal·종료·compaction) + 필요시 ' + CSRC + ' 실제 파일 + ' + P + '\\graph.py·agent.py.\n' +
'점검: 루프 종료조건·terminal 사유·재시도/루프가드·컨텍스트 관리가 claudecode 패턴과 정합한가, 배울 점/누락. findings·strengths·evidence(claude src 인용).' },
  { key: 'cc_tools', label: '검증:claude도구패턴', prompt:
'가늠터 도구 설계가 claudecode/opencode 도구 패턴과 정합한지 대조. Read ' + CC + '(Grep 도구·tool·권한·결과포맷·스키마) + 필요시 ' + CSRC + ' + ' + P + '\\tools.py.\n' +
'점검: 도구 스키마·결과 포맷·에러처리·결과를 State/messages에 넣는 방식이 claudecode 패턴과 정합한가. findings·strengths·evidence.' },
  { key: 'dom_uijae', label: '검증:의제정확성', prompt:
'의제(인허가 의제) 트리거가 인허가 리서치와 맞는지 검수. Read ' + R + '\\PERMIT_FLOW_LAW_MAP.md(Grep §1 의제허브·§2 케이스트리·지목) + ' + R + '\\wf_data.py(UIJAE) + ' + P + '\\agent.py(_UIJAE/record_uijae)·tools.py.\n' +
'점검: 지목→전용법(전답과수원→농지전용, 임야→산지전용)·형질변경→개발행위·맹지→사도·입지의제 트리거가 리서치대로인가, 누락된 의제(하천/가축/도로점용 등). findings·strengths·evidence.' },
  { key: 'dom_docs', label: '검증:서류전수정확성', prompt:
'서류 전수(누락0)가 시행규칙 조문과 맞는지 검수. Read ' + R + '\\PERMIT_FLOW_LAW_MAP.md(Grep §12 누락방지·첨부조문) + ' + R + '\\wf_docs_agent.py(DOC_SOURCE/docs_for) + ' + P + '\\tools.py(docs_for_stage).\n' +
'점검: 건축허가§6①·착공§14·사용승인§16·농지전용§26②·개발행위§9①·산지전용§10② 호 전수가 정확한가, 단계 커버리지(completeness_guard), 누락 단계/조문. findings·strengths·evidence.' },
  { key: 'dom_act', label: '검증:행위제한/조례판정', prompt:
'행위제한·조례 판정 로직이 검증 리서치와 맞는지 검수. Read ' + R + '\\INTEGRATED_PERMIT_RESEARCH.md(Grep §5-D API커버리지·행위제한·조례위임) + ' + R + '\\PERMIT_FLOW_LAW_MAP.md(Grep §5 조례·트리거RAG) + ' + P + '\\tools.py(act_landuse)·graph.py(_derive_verdict).\n' +
'점검: 행위제한 API 신뢰도(법령직접=정확/조례위임=빈값)·"금지"=입지제한 보수처리·조례위임 감지→RAG·판정 등급화가 리서치대로인가. findings·strengths·evidence.' },
  { key: 'dom_rule', label: '검증:룰(규모/작성주체)', prompt:
'규모·작성주체·충돌처리 룰이 리서치와 맞는지 검수. Read ' + R + '\\PERMIT_FLOW_LAW_MAP.md(Grep §4-C 작성주체·§9-C 규모·면적임계) + ' + P + '\\tools.py(compute_scale/author_rule_tool)·graph.py.\n' +
'점검: 구조안전 200㎡↑/2층↑·에너지 500㎡↑·건축사 필수(§23① 85㎡↓증축/200㎡↓대수선 면제)·개발제한/결측 강등이 정확한가. findings·strengths·evidence.' },
  { key: 'exec_stub', label: '실행:stub광역', prompt:
'프로토타입을 stub(빠름)로 광역 실행해 강건성·과적합·다양성 검수. Bash 순차 실행:\n' +
'PYTHONIOENCODING=utf-8 uv run --directory ' + P + ' python run.py 3 8 stub\n' +
'PYTHONIOENCODING=utf-8 uv run --directory ' + P + ' python run.py 55 8 stub\n' +
'점검: 16샘플 크래시0·빈카드0·지목 다양(전/답/임야/대 등)·용도지역 다양·의제판정 합리(전답→농지전용·임야→산지전용·대→없음)·서류 전수확보. findings(크래시/비합리/과적합)·strengths(수치 인용)·evidence. law.go.kr 느림 인내.' },
  { key: 'exec_real_jimok', label: '실행:실LLM다지목', prompt:
'실 LLM(gpt-5.2)로 여러 지목 e2e 검수(느림 건당~2-3분, 인내). 좌표 직접 주려면 trace.py 사용. Bash:\n' +
'PYTHONIOENCODING=utf-8 uv run --directory ' + P + ' python run.py 7 1\n' +
'PYTHONIOENCODING=utf-8 uv run --directory ' + P + ' python run.py 21 1\n' +
'PYTHONIOENCODING=utf-8 uv run --directory ' + P + ' python run.py 34 1\n' +
'점검: 실 LLM agent=LLM(GMS gpt-5.2) 확인·무한루프 없이 종료·도구 자율선택·지목별 의제 합리·카드 정상. 각 run의 지목/용도지역/판정/의제/도구호출수 인용. findings·strengths·evidence. 실패 1회 재시도.' },
  { key: 'exec_real_jorye', label: '실행:실LLM조례멀티홉', prompt:
'실 LLM로 조례위임 멀티홉 e2e 검수(느림). Bash:\n' +
'PYTHONIOENCODING=utf-8 uv run --directory ' + P + ' python trace.py "경기도 양평군 용문면 다문리 100"\n' +
'PYTHONIOENCODING=utf-8 uv run --directory ' + P + ' python trace.py "강원특별자치도 춘천시 신북읍 율문리 100"\n' +
'점검: 행위제한 빈값→조례확인필요→ordin_byeolpyo_fetch→law_byeolpyo_fetch→record_ordinance_ruling 멀티홉 시퀀스 실제 발동·호목해소(제4호 자목=일반음식점)·최종 verdict 합리·트레이스 단계 노출. findings(멀티홉 미해소/오판)·strengths(해소 인용)·evidence. 실패 1회 재시도.' },
  { key: 'exec_edge', label: '실행:엣지/실패', prompt:
'엣지·실패 케이스 강건성 검수. Bash로 stub 광역에서 특이 케이스 관찰 + 카페 외 용도 1건:\n' +
'PYTHONIOENCODING=utf-8 uv run --directory ' + P + ' python run.py 100 10 stub\n' +
'그리고 ' + P + '\\graph.py·tools.py를 Read해 실패경로(지오코딩 실패→site_geocode_failed, 개발제한→위험금지, 맹지 roadSideCodeNm, API 빈값→확인필요, 카페외 용도→조례확인필요) 처리가 코드상 맞는지 교차.\n' +
'점검: 개발제한구역 샘플 나오면 위험금지인가·맹지 감지·실패시 기권·과적합(카페 전용) 여부. findings·strengths·evidence.' },
  { key: 'consistency', label: '검증:일관성', prompt:
'동일입력 일관성 검수. Bash:\n' +
'PYTHONIOENCODING=utf-8 uv run --directory ' + P + ' python run.py 42 1 stub\n' +
'PYTHONIOENCODING=utf-8 uv run --directory ' + P + ' python run.py 42 1 stub\n' +
'두 출력이 동일한지(결정적 stub) 비교. 그리고 ' + P + '\\graph.py·tools.py Read해 비결정 요소(append 순서·dict 순회·시각 등) 있는지 점검. findings(비결정성)·strengths(일관 확인)·evidence.' },
]
const results = (await parallel(DIMS.map(d => () =>
  agent(d.prompt, { schema: FIND, label: d.label, phase: '검증' })
))).filter(Boolean)
log('검증 완료: ' + results.length + '/' + DIMS.length + ' 차원')

phase('종합')
const SYNTH = {
  type: 'object',
  properties: {
    overall: { type: 'string' },
    implement_ready: { type: 'boolean' },
    spec_conformance: { type: 'string' },
    high_issues: { type: 'array', items: { type: 'string' } },
    prioritized_fixes: { type: 'array', items: { type: 'object', properties: {
      priority: { type: 'string' }, file: { type: 'string' }, change: { type: 'string' }
    }, required: ['priority', 'change'] } },
    verified_strengths: { type: 'array', items: { type: 'string' } },
  },
  required: ['overall', 'implement_ready', 'prioritized_fixes'],
}
const synth = await agent(
'가늠터 ReAct 프로토타입 대규모 QA 17차원 결과를 종합하라.\n\n' + JSON.stringify(results) + '\n\n' +
'품질 최우선: overall(총평), implement_ready(boolean), spec_conformance(명세대로 구현됐나 한줄), high_issues(치명/중대), prioritized_fixes(priority high/med/low·file·change 구체), verified_strengths(실증·대조로 확인된 강점). 중복 제거, 실행가능한 수정안으로. 도메인 정확성·LangGraph 정확성·실행 강건성·claude패턴 정합을 모두 반영.',
  { schema: SYNTH, label: '종합:품질리포트', phase: '종합' })

return { dims: results, synth, dimCount: results.length }
