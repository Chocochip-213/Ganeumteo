export const meta = {
  name: 'react-proto-qa',
  description: 'ReAct 프로토타입 품질 QA — 코드리뷰·스펙적합·멀티시드 강건성 병렬 → 종합 리포트+수정안',
  phases: [
    { title: 'QA', detail: '코드리뷰·스펙적합·멀티시드 실행 3병렬' },
    { title: '종합', detail: '품질 리포트 + 우선순위 수정안' },
  ],
}

const PROTO = 'C:\\Users\\kmw16\\Desktop\\agent\\probe\\react_proto'
const SPEC = 'C:\\Users\\kmw16\\Desktop\\agent\\probe\\research\\GANEOMTEO_IMPL_SPEC.md'

const FIND = {
  type: 'object',
  properties: {
    dimension: { type: 'string' },
    verdict: { type: 'string' },
    findings: { type: 'array', items: { type: 'object', properties: {
      severity: { type: 'string' }, loc: { type: 'string' }, problem: { type: 'string' }, fix: { type: 'string' }
    }, required: ['severity', 'problem', 'fix'] } },
    strengths: { type: 'array', items: { type: 'string' } },
  },
  required: ['dimension', 'verdict', 'findings'],
}

phase('QA')
const dims = [
  { key: 'code', label: 'QA:코드리뷰', prompt:
'react_proto ReAct 프로토타입 코드 품질을 적대적으로 검수하라. Read: ' +
PROTO + '\\state.py, ' + PROTO + '\\tools.py, ' + PROTO + '\\agent.py, ' + PROTO + '\\graph.py, ' + PROTO + '\\run.py.\n' +
'점검: (1)버그(런타임/로직) (2)과적합(특정 지목/용도/지역에만 동작? 케이스값 하드코딩?) (3)에러처리(API 실패·빈값·예외·재시도) (4)LangGraph API 정확성(Command(update)·ToolNode·InjectedToolCallId·add_messages 리듀서·StateGraph 조건부엣지·recursion) (5)도구→State 데이터브리지(도구 Command가 타입필드 실제 채우나, completeness_guard/build_reasoning이 읽는 필드와 일치하나).\n' +
'findings에 severity(high/med/low)·loc(파일:함수)·problem·fix(구체). strengths도. verdict=pass/issues. 봐주지 말고 빡세게.' },
  { key: 'spec', label: 'QA:스펙적합', prompt:
'프로토타입이 구현명세대로 됐나 검수. Read 명세 ' + SPEC + ' (Grep으로 부록 G ReAct·G2.1 Command브리지·G2.2 request_human_input·E build_reasoning·D2 종료계약·§3 State 찾아 읽기) + react_proto 코드(' + PROTO + ' 의 state/tools/agent/graph py).\n' +
'점검: 명세 대비 (1)누락(스펙 노드/도구/필드 중 프로토타입에 없는 것 — request_human_input·reg_effect_resolve·finalize/abstain 배선 등) (2)불일치(이름·시그니처·흐름·State 필드명 D0.3 정규) (3)핵심 미구현(멀티홉=조례별표+건축법령별표1→호목해소 / 완결성가드 / 환각가드=citation 없으면 abstain 기권 / build_reasoning 결정적 골격). (4)프로토타입이라 단순화 OK인 것 vs 빠지면 안되는 것 구분.\n' +
'findings(severity·loc·problem·fix)·strengths·verdict.' },
  { key: 'exec', label: 'QA:멀티시드실행', prompt:
'프로토타입 강건성을 실제 실행으로 검수. Bash로 순차 실행:\n' +
'(A) 빠른 광역(stub=LLM우회, 과적합·강건성): PYTHONIOENCODING=utf-8 uv run --directory ' + PROTO + ' python run.py 5 6 stub\n' +
'(B) 또 다른 시드 광역: PYTHONIOENCODING=utf-8 uv run --directory ' + PROTO + ' python run.py 88 6 stub\n' +
'(C) 실 LLM ReAct 확인(느림 건당 ~2분): PYTHONIOENCODING=utf-8 uv run --directory ' + PROTO + ' python run.py 7 1\n' +
'점검: (1)크래시/예외(ERROR/traceback) 없나 (2)랜덤 지역마다 카드 산출(과적합 아님 — 12개 광역 샘플) (3)지목·용도지역 다양성(전/답/임야/대/녹지/관리/상업 등 여러개 나오나) (4)판정 합리성(개발제한→위험금지, 농지(전답)→농지전용 의제, 임야→산지전용, 대→의제없음) (5)도구호출수·citations·서류 전수확보 정상 (6)실 LLM(C)이 무한루프 없이 종료하고 합리적 카드 내나.\n' +
'각 run 출력을 근거로 findings(문제: 크래시/빈카드/비합리판정/과적합징후/LLM 의제누락)·strengths(작동확인 사실, 수치 인용)·verdict. ⚠️ law.go.kr 느림/연결리셋 가능 — 실패 run은 1회 재시도.' },
]
const results = (await parallel(dims.map(d => () =>
  agent(d.prompt, { schema: FIND, label: d.label, phase: 'QA' })
))).filter(Boolean)
log('QA 완료: ' + results.length + '/3 차원')

phase('종합')
const SYNTH = {
  type: 'object',
  properties: {
    overall: { type: 'string' },
    implement_ready: { type: 'boolean' },
    high_issues: { type: 'array', items: { type: 'string' } },
    prioritized_fixes: { type: 'array', items: { type: 'object', properties: {
      priority: { type: 'string' }, file: { type: 'string' }, change: { type: 'string' }
    }, required: ['priority', 'change'] } },
    strengths: { type: 'array', items: { type: 'string' } },
  },
  required: ['overall', 'implement_ready', 'prioritized_fixes'],
}
const synth = await agent(
'ReAct 프로토타입 QA 3차원 결과를 종합해 품질 리포트를 내라.\n\n' + JSON.stringify(results) + '\n\n' +
'품질 최우선 관점에서: overall(한 문단 총평), implement_ready(boolean — 프로토타입으로서 "ReAct 동작 증명" 목적에 충분한가), high_issues(치명/중대 목록), prioritized_fixes(우선순위 high/med/low·file·change 구체), strengths(검증된 강점). 중복 제거하고 실행가능한 수정안으로.',
  { schema: SYNTH, label: '종합:품질리포트', phase: '종합' })

return { dims: results, synth }
