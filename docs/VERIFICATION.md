# 검증 기록

2026-10-28 · macOS arm64 · OMP 18.12.6

| 검증 | 결과 |
|---|---|
| 실행기 단위·회귀 검사 | Python 25개 + 쓰기 어댑터 8개; 4회 연속 전부 통과 |
| 설치·복구 반복 | Qwen 고정 리비전의 가중치 4개 SHA-256 검증; setup.sh 재실행 정상 |
| 실제 Claude 총괄 호출 | Opus 5.5/high 응답 확인 |
| 실제 파트 실행 | Sonnet 독립 작업 병렬 → 선행 결과 전달 → 파일 생성 → Python 검사 통과 |
| 일반 omp 진입 | 프로젝트 자동 로드 → Opus가 Qwen 라벨·Codex 구현·Sonnet 문서로 분해 → 바이트·함수 실행·문서 일치 검사 모두 통과 |
| 실패·재개 | 의도적 검사 실패 → 후속 차단 → 같은 run_id에서 수정 → 재검사·후속 실행 통과 |
| 심화 프로필 | GPT-6.1 Sol/high, GPT-6 Astra/high·xhigh, Sonnet 5.5/high 실제 호출 통과 |
| 대화형 진입 | 일반 omp 실행 후 Opus 5.5/high·AgentMesh 상태·mesh-doctor 명령 확인 |
| 실제 속도 전달 | Claude speed/service_tier 미설정 확인. Codex CLI fast 설정으로 실제 작업 성공; OMP 경로 priority 전송도 별도 확인 |
| Codex 성공 호출 | 기존 Codex CLI 어댑터로 구현·파일 생성·Python 검사 통과. OMP 저장 계정의 한도 오류는 별도 실패·후속 차단으로 확인 |
| Qwen 실호출 | Thinking on 확인; 한국어 파일 수정 → 정확한 바이트 검사 → Codex JSON 통합 검사 2회 통과 |
| 로컬 쓰기 회귀 | XML 문자열 끝 줄바꿈 제거 재현; 줄 배열·종단 LF 분리 후 13바이트 검사 통과. 공백·빈 줄·범위 밖 경로·심볼릭 링크·파일 권한 검사 통과 |
| 강제 종료·복구 | 로컬 서버 실행 중 실행기 강제 종료 → 서버 정리 → interrupted 감지 → 같은 run_id 재개·완료 확인 |
| 애니메이션 | 전체 1,210프레임 디코딩 및 생성 원본과 픽셀 비교 일치; 반복·크기·프레임 시간 확인 |

원시 실행 기록·사용량·계정별 정보는 로컬 `.agentmesh/`에만 보관합니다.
