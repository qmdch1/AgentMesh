# 실행·복구 계약

| 구성 | 실제 동작 |
|---|---|
| 시작 | `~/.omp/agent/extensions/agentmesh.ts` 전역 자동 로드; 어느 프로젝트에서든 Opus 5.5/high 고정. 설치 전 열린 세션은 재시작 |
| 설치 위치 | `~/.omp/agentmesh`에 실행 코드·모델·기록 보관. 원본 저장소 경로와 독립; 저장소 `.agentmesh`는 공유 상태 심볼릭 링크 |
| 속도 | Claude 일반, Codex Fast(`service_tier=fast`). 전역 설정의 기존 부가 항목 보존·변경 전 백업 |
| 작업 폴더 | OMP 실행 위치를 총괄에 명시; 각 프로젝트 AGENTS.md/CLAUDE.md를 확인한 뒤 해당 폴더를 작업 대상으로 사용 |
| 모델 표시 | `agentmesh-local/Qwen3.6-35B-A3B 4bit`; 어느 폴더에서든 `omp models agentmesh-local`로 확인 |
| 계정 | Claude는 OMP 인증, Codex는 기존 CLI 인증 사용. AgentMesh는 로그인 토큰·비밀번호를 읽거나 복제하지 않음 |
| 프로필 | `scripts/agentmesh/profiles.json`; 실행마다 모델·강도 명시, 다른 모델로 자동 대체 금지 |
| 실행 | `mesh_run`이 독립 읽기 작업 최대 3개 병렬, 쓰기 작업 직렬 실행. Claude/Qwen은 작업별 OMP 프로세스, Codex는 작업별 ephemeral CLI 실행; 모두 별도 문맥 사용 |
| 문맥 | 공통 제약 + 해당 작업 + 명시한 텍스트/이미지 + 선행 결과만 전달; 전체 대화 복제 없음 |
| 검사 | 실행기가 지정된 argv 검사 명령 실행; 종료 코드·변경 범위·실제 모델 ID·공급자 오류로 성공 판정 |
| 로컬 | Qwen MLX 4bit를 loopback 전용 서버로 로드. 로컬 작업 잠금 유지, 종료·취소 시 서버 종료 |
| 로컬 쓰기 | `mesh_write(lines, final_newline)`로 줄바꿈 보존·허용 경로 확인·원자적 교체. 원시 XML 문자열의 끝 줄바꿈 제거를 우회; 셸 도구 없음 |
| 영속 기록 | `.agentmesh/runs/<run_id>/`에 계획·상태·작업자 출력·검사 결과. Git에서 제외 |
| 재개 | `mesh_status`로 run_id 확인 후 동일 run_id와 전체 수정 계획을 `mesh_run`에 전달; 계획·공통 조건·관련 파일이 같은 성공 작업만 재사용 |
| 실패 | 선행 실패 시 후속 작업 차단. 모델 한도·연결·검사 실패를 성공으로 표시하지 않음 |
| 재시도 | 작업별 최대 3회, 기본 작업 600초·전체 1800초. 모델 로드·검사 포함 남은 시간 적용; 재개 시 원래 전체 시간·시도 예산 보존 |
| 취소 | 취소 신호를 작업자에 전달하고 로컬 서버 해제; 부모 종료 감지; 중단 실행 자동 재시작 없음 |
| 한계 | 계정 로그인 만료·사용량 한도·공급자 변경·네트워크 장애는 자동 설치로 제거할 수 없음. 검사·검토 누락은 통과 근거가 아님 |

모델 가중치는 최초 설치 시 공식 저장소의 리비전을 고정하고 SHA-256을 검증합니다. 설치·복구: `./scripts/setup.sh`. 실행기 회귀 검사: `./scripts/verify.sh`.

텍스트 쓰기 어댑터 검사: `node --test tests/scoped_write.test.mjs`. Node가 있으면 `verify.sh`에서도 함께 실행하며, 별도 경로는 `AGENTMESH_NODE`로 지정합니다. [MLX의 Qwen 도구 파서](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/tool_parsers/qwen3_coder.py).

Codex CLI는 응답 이벤트에 모델 식별자를 포함하지 않으므로, 기록의 model_source에 명시적 CLI 인자로 선택한 모델임을 표시합니다. OMP 작업자는 응답 메타데이터의 모델을 확인합니다.
