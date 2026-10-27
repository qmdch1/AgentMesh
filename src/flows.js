export const nodes = {
  omp: { name: 'OMP', role: '요청 진입점', tag: 'ENTRY', x: 28, y: 218, color: 'mint', description: '사용자의 요청을 받아 로컬 라우터로 전달하고, 검증된 최종 결과를 반환하는 오케스트레이션 진입점입니다. 이 데모에서는 특정 OMP 제품의 실제 동작을 가정하지 않습니다.' },
  router: { name: 'Local Router', role: '로컬 라우터', tag: 'ROUTING', x: 218, y: 218, color: 'mint', description: '작업 유형과 복잡도를 기준으로 실행 경로를 결정합니다. 가벼운 작업은 로컬에 유지하고, 구현과 설계 작업은 적합한 전문 에이전트로 전달합니다.' },
  q4: { name: 'Qwen 4B', role: '빠른 분류 · 간단한 응답', tag: 'LOCAL / SMALL', x: 420, y: 98, color: 'mint', description: '빠른 요청 분류, 짧은 요약, 간단한 질의응답을 담당하는 소형 로컬 모델 역할입니다. 복잡한 요청은 라우터를 통해 상위 경로로 전달합니다.' },
  q35: { name: 'Qwen 35B', role: '문맥 분석 · 초안 생성', tag: 'LOCAL / LARGE', x: 420, y: 338, color: 'mint', description: '긴 문맥 분석과 로컬 초안 생성을 담당하는 대형 로컬 모델 역할입니다. 모델 이름은 아키텍처상의 표시이며 특정 배포판이나 성능을 보장하지 않습니다.' },
  codex: { name: 'Codex', role: '코드 구현 · 수정', tag: 'CLOUD / CODE', x: 660, y: 98, color: 'lavender', description: '로컬에서 정리한 요구사항을 받아 코드 구현과 수정 작업을 수행하는 전문 에이전트 역할입니다. 결과는 검증 단계를 거칩니다.' },
  claude: { name: 'Claude', role: '설계 · 복잡한 추론', tag: 'CLOUD / REASON', x: 660, y: 338, color: 'lavender', description: '복잡한 요구사항의 설계와 검토를 맡는 전문 에이전트 역할입니다. 설계 결과를 검증하고 필요한 경우 구현 에이전트와 연결할 수 있습니다.' },
  verify: { name: 'Verification', role: '검증 · 품질 확인', tag: 'QUALITY GATE', x: 660, y: 218, color: 'orange', description: '생성한 응답과 코드의 요구사항 충족 여부를 확인합니다. 데모의 통과와 실패는 미리 정의된 예시이며, 실제 운영에서는 테스트·정적 분석·정책 검사 등을 연결해야 합니다.' },
};
const hop = (from, to, label, kind = 'local') => ({ from, to, label, kind });
const entry = [hop('omp', 'router', '요청 접수 · 작업 유형 확인'), hop('router', 'q4', 'Qwen 4B로 요청 분류')];
const finish = [hop('verify', 'omp', '검증 통과 · 최종 결과 반환', 'verified')];
export const scenarios = [
  { id: 'quick', icon: '↯', title: '빠른 로컬 응답', subtitle: '분류 · 요약 · 간단한 질문', route: 'LOCAL ONLY', prompt: '“이 문서의 핵심 내용을 세 문장으로 요약해 줘.”', steps: [...entry, hop('q4', 'verify', '간단한 요청 · 로컬 응답 검증'), ...finish] },
  { id: 'context', icon: '▤', title: '깊이 있는 로컬 분석', subtitle: '긴 문맥 · 분석 · 초안 작성', route: 'LOCAL ONLY', prompt: '“프로젝트 문서를 분석해서 구현 요구사항을 정리해 줘.”', steps: [...entry, hop('q4', 'router', '긴 문맥 감지 · 상위 로컬 모델 요청'), hop('router', 'q35', 'Qwen 35B에 문맥 분석 위임'), hop('q35', 'verify', '분석 결과와 초안 검증'), ...finish] },
  { id: 'code', icon: '⌘', title: '코드 구현', subtitle: '로컬 준비 → Codex → 검증', route: 'HYBRID', prompt: '“로그인 API를 구현하고 테스트도 작성해 줘.”', steps: [...entry, hop('q4', 'router', '코드 구현 작업으로 분류'), hop('router', 'q35', '로컬에서 요구사항과 문맥 정리'), hop('q35', 'codex', 'Codex에 구현 위임', 'cloud'), hop('codex', 'verify', '구현 결과 · 테스트 검증', 'cloud'), ...finish] },
  { id: 'design', icon: '◇', title: '아키텍처 설계', subtitle: '로컬 준비 → Claude → 검증', route: 'HYBRID', prompt: '“빠른 응답과 결과 품질을 함께 고려한 에이전트 구조를 설계해 줘.”', steps: [...entry, hop('q4', 'router', '복합 설계 요청으로 분류'), hop('router', 'q35', '설계에 필요한 제약과 문맥 정리'), hop('q35', 'claude', 'Claude에 설계와 추론 위임', 'cloud'), hop('claude', 'verify', '설계의 요구사항 충족 여부 검증', 'cloud'), ...finish] },
  { id: 'retry', icon: '↻', title: '검증 실패와 재작업', subtitle: '실패 감지 → 수정 → 재검증', route: 'RECOVERY', prompt: '“실패한 테스트를 수정하고, 통과 여부를 다시 확인해 줘.”', steps: [...entry, hop('q4', 'router', '코드 수정 작업으로 분류'), hop('router', 'codex', 'Codex에 수정 위임', 'cloud'), hop('codex', 'verify', '수정 결과의 테스트 실행', 'cloud'), hop('verify', 'codex', '검증 실패 · 실패 내용을 첨부해 재작업', 'retry'), hop('codex', 'verify', '수정 완료 · 재검증', 'cloud'), ...finish] },
];
export function edgeKey(from, to) { return `${from}-${to}`; }
export function allEdges() {
  return [...new Map(scenarios.flatMap(s => s.steps).map(s => [edgeKey(s.from, s.to), s])).values()];
}
// A pure state transition keeps stepping, replaying and scenario switching deterministic.
export function advance(state, length) {
  const index = Math.min(state.index + 1, length);
  return { index, status: index === length ? 'complete' : 'paused' };
}
