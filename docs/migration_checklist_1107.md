<!-- short: 11/7 전환, 겸이 할 일 순서 -->
<!-- oneliner: 클릭 11단계 약 90분(시크릿 재입력 25분이 최대) · 막히면 변수 2개로 5분 롤백 -->

# 11/7(토) 저장소 전환 체크리스트 — 겸이용

작성 2026-11-01 KST · 개발 데스크 · 결재 11/1 18:08(「싹다승인」) · 근거 `docs/refactor_plan_v1.md` §6·§7, `docs/refactor_v1_inventory.md` §1-1·§2·§4·§5
결정 반영: D1 옛 저장소 이름 변경 → 새 공개 저장소가 `market-screener` 이름 승계 · D2 개인 시크릿 워크플로는 11/7엔 범용판에 그대로(pick·pb_call 만 내부판) · D3 옛 브랜치 9개 안 가져감 · ② 노트북 계속 사용 → **전환 뒤 새 저장소로 다시 설치**.
값(토큰·키·비밀번호)은 이 문서·채팅·저장소 어디에도 적지 않는다 — 이름만.

## 상단 (STANDARD 8절)
- **What**: 겸이 손으로 하는 일 11단계, 합계 약 90분. 개발이 미리 끝낸 것: 전역 무음 변수 `ALERTS_OFF`, 범용판 빌드(내부 탭 9개 숨김), 이전 스크립트 `scripts/migrate_v1.py`, 텔레그램 이슈 저장소 속성 `TG_ISSUE_REPO`.
- **So What**: 이름을 그대로 넘겨받아 Pages 주소·GAS·노트북 주소가 안 바뀐다 → 바꿀 것은 **시크릿·토큰·변수**뿐. 가장 긴 일은 시크릿 23개 재입력(옛 저장소 화면에선 값을 다시 볼 수 없다 — 원래 발급처에서 가져와야 함).
- **Now What**: 11/6(금) 밤까지 아래 '사전 준비' 3개 → 11/7 오전(장 없음) 1~9단계 → 11/9~11 아침 PM 한 줄만 확인 → 11/14 이후 10단계(비공개 전환). 막히면 맨 아래 롤백.

## 사전 준비 (11/6 금 밤까지, 15분)
- [ ] 시크릿 값 23개를 꺼낼 수 있는지 확인(값은 화면에 띄우기만, 어디에도 붙여 두지 않기). 출처: DART·ECOS·공공데이터포털·KRX·한국부동산원·브이월드 = 각 사이트 '마이페이지/인증키' · 텔레그램 봇 토큰 = BotFather `/mybots → API Token` · 채팅 ID = 기존 값 · `CLASPRC_JSON` = 노트북 `~/.clasprc.json` · GAS ID 3개 = Apps Script 프로젝트 설정 · `GCP_SA_JSON` = GCP 콘솔 서비스 계정 키(잃었으면 새 키) · `MY_*`·`RULE_*` = 지금 쓰는 값(비공개 저장소 기준)
- [ ] 개발 '준비 끝' 한 줄 확인(텔레그램/사내톡): `migrate_v1.py` dry-run 막힘 0 · 감사 확인 끝
- [ ] 옛 토큰은 **지우지 않는다**(11/14까지 — 롤백용)

## 전환 순서 (11/7 토 오전)
| # | 할 일 | 어디를 누르나 | 분 | 확인 |
|---|---|---|---|---|
| 1 | 옛 저장소 이름 변경 → `market-screener-desk`(예시, 바꿔도 됨) | 옛 저장소 → **Settings → General → Repository name** → Rename | 2 | 주소창이 새 이름. 이 순간부터 GAS·노트북 실행 요청은 대상 없음 → 옛 쪽 cron 대기(+12분)가 대신 돎(정상) |
| 2 | 새 공개 저장소 `market-screener` 만들기 | github.com **+ → New repository** → Owner `hk99915-bot` · Name `market-screener` · **Public** · README/.gitignore/License **모두 체크 해제** → Create | 3 | 빈 저장소 화면 |
| 3 | 개발에게 "만들었어" 한 줄 → 개발이 스냅샷 1커밋 push(`migrate_v1.py --apply` 결과) | (겸이 클릭 없음) | 10 대기 | 새 저장소 Code 탭에 파일·`.edition` 보임. 세션이 새 저장소에 못 쓰면 개발이 노트북용 명령 1줄을 줌 |
| 4 | 새 저장소 **변수 6개** 먼저: `DATA_BRANCH_KR`·`DATA_BRANCH_US`·`KRX_BACKEND`·`PAGES_ACTIONS`·`VWORLD_DOMAIN`(옛 저장소 값 그대로 — 변수는 옛 화면에서 보임) + **`ALERTS_OFF` = `1`**(무음으로 시작) | 새 저장소 → **Settings → Secrets and variables → Actions → Variables 탭 → New repository variable** | 4 | 변수 6개 |
| 5 | 새 저장소 **시크릿 23개** | 같은 화면 **Secrets 탭 → New repository secret** — 아래 표 순서 | 20~25 | 개수 23. **`RISK_PCT`·`SAT_BOOK_KRW` 는 넣지 않음**(내부판 전용) |
| 6 | Pages 켜기 | 새 저장소 → **Settings → Pages → Build and deployment → Source: Deploy from a branch → Branch `main` / `(root)` → Save** | 3 | 1~3분 뒤 `hk99915-bot.github.io/market-screener/` 열림 · 상단 탭에 MY·LIFE·STUDY·SYSTEM 없음(범용판) |
| 7 | 미세 토큰 4개 새로 | 오른쪽 위 프로필 → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token** — 아래 토큰 표 | 10 | 만료일 설정·저장소 1개만 |
| 8 | GAS 속성 교체 + `tickTest` | script.google.com → **예약기 프로젝트 → ⚙ 프로젝트 설정 → 스크립트 속성 → 속성 수정**: `GH_TOKEN`(토큰①) 교체 · `TG_ISSUE_REPO` = `hk99915-bot/<1번 새 이름>` 추가 · `GH_ISSUE_TOKEN`(토큰④) → 저장 → 편집기에서 함수 **`tickTest` → 실행** / **웹앱 프로젝트(Code.gs)** 속성 `GITHUB_TOKEN`(토큰③) 교체 | 10 | 로그 첫 줄 `예약기 버전 …` + 오늘 시간표 줄. 편집기에서 `tgIssueRepo_` 검색 → 없으면 저장소 `apps-script/TelegramHook.gs` 전체 붙여넣기 |
| 9 | 알림 넘기기(변수 2개) | ① **옛** 저장소 Variables → `ALERTS_OFF` = `1` 추가 ② **새** 저장소 Variables → `ALERTS_OFF` 삭제 ③ 새 저장소 **Actions → telegram_test → Run workflow** | 5 | 텔레그램 '연결 테스트 성공' 1통. 옛 쪽 실행 로그엔 `ALERTS_OFF=1 — 텔레그램 발송 생략` |
| 10 | 노트북 다시 설치(② 계속 사용) | PowerShell: `Stop-ScheduledTask gh_dispatch,toss_md_live,toss_md_sectors` → `Rename-Item $HOME\market-screener market-screener-old` → `git clone https://github.com/hk99915-bot/market-screener.git $HOME\market-screener` → `notepad $HOME\.config\gh_dispatch\env` 에서 `GH_DISPATCH_TOKEN=` 값을 토큰②로 → `python tools\dispatch\dispatch.py --dry-run` → `Start-ScheduledTask gh_dispatch` | 15~20 | 토스 키(`$HOME\.config\toss_md\env`)는 저장소 밖이라 그대로. 첫 `--publish` 때 브라우저 로그인 1회. `Get-ScheduledTask gh_dispatch,toss_md_* \| Get-ScheduledTaskInfo` → `LastTaskResult` 0 |
| 11 | 옛 저장소 워크플로 끄기 — **지금은 안 함** | 11/11 밤 개발이 '옛 쪽에서 끌 워크플로 목록'(내부판 8개 빼고 전부)을 줌 → 그때 옛 저장소 **Actions → 워크플로 선택 → '…' → Disable workflow** | 0 | 병행 기간엔 옛 쪽도 돌아야 대조 가능(알림만 무음) |

- 합계 약 85~95분(3번 대기 포함). 9번까지 끝나면 텔레그램은 새 쪽만 울린다. 3~4번 사이 새 쪽 예약 실행은 텔레그램 시크릿이 아직 없어 보내지 못하므로 이중 발송 없음.
- 11/9(월)~11/11(수): 아침 PM 병행 판정 한 줄만 본다(숫자 불일치 0 3일 연속이 기준). 이상하면 '롤백' 한 단어.
- **11/14(토) 이후**: 옛 저장소 **Settings → General → Danger Zone → Change visibility → Private**(2분) · Claude 설정에서 세션 저장소에 내부판 추가(3분).

### 시크릿 23개 (이름만 — 값 금지)
| 묶음 | 이름 | 개수 |
|---|---|---|
| 데이터 키 | `DART_API_KEY` `DATA_GO_KR_KEY` `ECOS_API_KEY` `KRX_API_KEY` `KRX_ID` `KRX_PW` `REB_API_KEY` `SEC_USER_AGENT` `VWORLD_KEY` | 9 (`KRX_API_KEY` 는 옛 저장소에도 없으면 건너뜀) |
| 텔레그램 | `TELE` `TELE_CHAT` `TELEGRAM_TOKEN` `TELEGRAM_CHAT_ID` | 4 (두 쌍 같은 값) |
| 개인 규칙(D2 현행) | `MY_HOLDINGS` `MY_RULES` `RULE_DEADLINE` `RULE_STOP_LEVEL` | 4 |
| GAS 배포 | `CLASPRC_JSON` `GAS_SCRIPT_ID` `GAS_SCHED_SCRIPT_ID` `GAS_DEPLOYMENT_ID` | 4 |
| Google 시트 | `GCP_SA_JSON` `GSHEET_ID` | 2 |
| **넣지 않음** | `RISK_PCT` `SAT_BOOK_KRW` (pick 전용 → 내부판에 이미 있음) | — |

### 토큰 4개 (Fine-grained, 만료일 꼭 설정)
| # | 쓰는 곳 | Repository access | Permissions | 넣는 곳 |
|---|---|---|---|---|
| ① | GAS 예약기 | Only select → `market-screener`(새) | Actions: Read and write | 예약기 속성 `GH_TOKEN` |
| ② | 노트북 dispatcher | Only select → `market-screener`(새) | Actions: Read and write | `$HOME\.config\gh_dispatch\env` |
| ③ | GAS 웹앱(Code.gs) | Only select → `market-screener`(새) | Contents: Read-only | 웹앱 속성 `GITHUB_TOKEN` |
| ④ | 텔레그램 훅(ask·study·pick 이슈) | Only select → 1번 새 이름(내부판) | Issues: Read and write | 예약기 속성 `GH_ISSUE_TOKEN` — 기존 `GH_ISSUE_TOKEN` 이 있으면 옛 저장소 ID에 묶여 있어 그대로 써도 됨(새로 안 만들어도 됨) |

- 미세 토큰은 저장소 이름이 아니라 **저장소 자체**에 묶인다 `[규정-B: GitHub 문서, 원문 재확인 전]` → 옛 토큰은 이름이 바뀐 내부판을 계속 가리킨다. 그래서 ①②③은 새로, ④는 재사용 가능.

## 롤백
| 상황 | 할 일 | 분 |
|---|---|---|
| 알림이 두 번 오거나 새 쪽 알림이 이상 (기본 롤백 — **변수 2개**) | ① **새** 저장소 Variables → `ALERTS_OFF` = `1` ② **옛** 저장소 Variables → `ALERTS_OFF` 삭제 | 5 |
| 새 쪽 실행 자체가 깨짐(데이터·화면) | 위 2개 + 새 저장소 **Settings → General** 이름을 `market-screener-new` 로 → 옛 저장소 이름을 `market-screener` 로 되돌림 → GAS 속성 `GH_TOKEN`·`GITHUB_TOKEN` 을 옛 토큰으로(지우지 않았으므로) · `TG_ISSUE_REPO` 삭제 · 노트북 `market-screener-old` 폴더 이름 원래대로 + `GH_DISPATCH_TOKEN` 옛 값 | +15 |
| Pages 가 안 뜸 | 6번 다시(브랜치 `main` / `(root)`) · 3분 기다림 · 그래도 안 되면 개발 호출(옛 Pages 는 `/<새 이름>/` 경로에서 계속 열림) | 5 |
| 노트북 clone·로그인 실패 | `market-screener` 지우고 `market-screener-old` 이름 원래대로 → 작업 스케줄러 그대로 돎(옛 쪽 대상이라 실행 요청은 실패 → GAS·cron 이 대신) | 5 |

- 롤백 판단은 겸이 한 단어('롤백'). 개발·PM 은 그 뒤 원인 정리만 한다. 이력 재작성·저장소 삭제는 어떤 경우에도 하지 않는다.
