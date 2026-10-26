# 요청 장부 정리 — 2026-10-26 (PM)

> 지시: 겸이 10/26 "지금 ㄱㄱ" — 화 토큰 긴축 회의 안건 '요청 장부 정리' 선착수. P2 일괄 이월 없음(겸이 결정: "화요일 23시 이후 풀가동으로 극복") → 목적은 미루기가 아니라 **실제로 남은 일**을 드러내기.
> 방법: `docs/desk_kb/rounds/_requests.json` 열린 요청 전수를 스크립트로 뽑고, 건마다 커밋(`git log --grep <id>`)·파일(`git grep <id>`, 대상 파일 직접 확인)·보드 상태·장부 회신을 대조. 근거가 확인된 것만 닫음. 규칙·한도 변경 없음(분류만). 개인 금액·보유는 옮기지 않음(id 만).
> 기준: 2026-10-26 오후 KST, main 044d6421. 크기 S/M/L·깨움 수·토큰은 **PM 추정 [검증전]**.

## 0. 전제 정정
- 장부 전체 250건 중 **안 닫힌 것은 114건**(open 91 · promoted 23). 나머지 136건은 이미 done — '약 250건'은 장부 총건수.
- 보드 P1 미완 65건 중 '[요청 승격]' 은 29건. 그중 **6건은 요청이 이미 done 인데 보드만 '대기'** 로 남은 동기화 누락(§3).
- 관찰(사실만, 규칙 변경 제안 아님): promoted 22건 중 6건은 승격일에 **마감(due)이 아직 남아 있었음** — req-data-7ff634a5·req-data-866790c9·req-data-88dfbe9f·req-dev-0d73cae1·req-pb-23606b98(due 10/28), req-frm-60f6b60e(due 11/14). 승격이 due 가 아니라 요청일+영업일 기준으로 도는 것으로 보임 [확인 필요: watchdog 승격 조건 코드 — 화 회의 안건 재료].

## 1. 분류별 건수 (114건)
| 분류 | 건수 | 처리 |
|---|---|---|
| (a) 이미 처리됨 | 1 | 닫음 |
| (b) 중복 | 4 | 원본 id 회신 남기고 닫음 |
| (c) 낡음/대체됨 — 폐기 후보 | 4 | **닫지 않음** — 결재 겸이 |
| (d) 진짜 남은 일 | 105 | §5 — S 45 · M 47 · L 13 |

(a)가 1건뿐인 이유: '부분 완료'(회신으로 일부 끝, 나머지 남음)는 닫지 않고 (d)에 '남은 부분'만 적음 — 데이터 5건·개발 3건·부동산·내무 각 1건 등.

## 2. 닫은 요청 (5건) — 근거
| id | 분류 | 닫은 데스크 | 근거 |
|---|---|---|---|
| req-pb-71d9c381 | (a)+(b) | pb | ① sec-ytd-bug 최종 판정 보드 notes 기재(8ad036b6, 보드 완료) ② PB 복기 `docs/desk_kb/pb.md` 12행으로 이전(10/23) ③ pb_view 문구 결정은 **req-pb-8a75f2cf**(열림)가 이어받음 |
| req-data-f6109a58 | (b) | data | 원본 **req-data-a555e088** — 'ECOS·KRX 접속 열림, 백필 가능' 알림이라 원본에 흡수(백필은 미완: bonds_hist 2022 행 0) |
| req-dev-228cac19 | (b) | dev | 원본 **req-dev-d1b2e934**(event_watch FUT 오래됨) — 파생 규격(원인 분류·max_age 120s/상한 300s)은 원본 처리 때 적용 |
| req-dev-2b62ee7b | (b) | dev | 원본 **req-dev-56e317b9** — 같은 `docs/sectors_switch_2026-10-24.md` 3행 정정 포함(아직 미정정 확인, 원본 열림) |
| req-hf-ab25efa4 | (b) | hf | 원본 **req-hf-20777b29** — 같은 3필드(시간 청산일·논지 붕괴·IV 재평가). 검증 쪽 키 이름·10/30 '주의' 조건은 원본 처리 때 반영 |

각 건에 PM 회신(대행 표기, VOC 아님)으로 원본 id 를 남김.

## 3. 보드 '[요청 승격]' 완료 처리 (7건)
req-data-2964da3f · req-data-4e390b32 · req-data-5046a78b · req-data-751d13c7 · req-dev-8d80aab2 · req-pm-1dc0d451(요청 이미 done, 보드만 대기) + req-pb-71d9c381(오늘 닫음) → `board.py --set … 완료`.
**보드 P1 미완 65 → 58** ('[요청 승격]' 29 → 22).

## 4. 폐기 후보 (4건 — 닫지 않음, 결재 겸이)
| id | 받는 쪽 | 사유 |
|---|---|---|
| req-cio-523f45e9 | cio | R2 판정용, 기한 10/18 14:00 지남(8일) — 아직 필요하면 새 요청으로 |
| req-peer-9b527d31 | peer | 알림 전용(G3·R4 결재 종결 통보) — 피어 할 일 없음, R3 집계는 10/30 정기 일정 |
| req-pb-9553d9b5 | pb | 결재 대상 Top 10(10/23 오후)이 같은 날 23시 재진단(`docs/uxui/2026-10-23_terminal_recheck.md`)으로 대체 — 새 Top 10 으로 다시 올릴지 |
| req-dev-71530ddf | dev | "이견 있으면 회신" 형 — 재배정은 이미 반영(82d1acbd, 보드 owner 프론트). 10/27 무회신이면 닫기 |

참고(폐기 아님, 확인 필요): req-dev-838025ff(10/21 밤 일회성 탐침) — 실행 흔적 미확인, 개발 S 로 '했나/안 했나' 1줄.

## 5. 데스크별 남은 일 (105건)
부하 = S1·M3·L8 점, 깨움 1회 ≈ 10점 처리로 가정. 토큰 = 깨움 × 10~16만(10/25 실측, 고정비 ≈5.4만 포함).
| 데스크 | 남은 건수 | S/M/L | 부하(S1·M3·L8) | 깨움 추정 | 토큰 추정(만) |
|---|---|---|---|---|---|
| data | 25 | 9/11/5 | 82 | 9 | 90~144 |
| dev | 17 | 7/6/4 | 57 | 6 | 60~96 |
| front | 6 | 2/3/1 | 19 | 2 | 20~32 |
| household | 5 | 1/3/1 | 18 | 2 | 20~32 |
| realestate | 5 | 0/5/0 | 15 | 2 | 20~32 |
| pb | 9 | 7/2/0 | 13 | 2 | 20~32 |
| derivs | 2 | 0/1/1 | 11 | 2 | 20~32 |
| frm | 4 | 1/3/0 | 10 | 1 | 10~16 |
| eval | 6 | 5/1/0 | 8 | 1 | 10~16 |
| macro | 1 | 0/0/1 | 8 | 1 | 10~16 |
| hf | 3 | 1/2/0 | 7 | 1 | 10~16 |
| verify | 2 | 0/2/0 | 6 | 1 | 10~16 |
| bonds | 3 | 2/1/0 | 5 | 1 | 10~16 |
| life | 2 | 1/1/0 | 4 | 1 | 10~16 |
| behavior | 2 | 1/1/0 | 4 | 1 | 10~16 |
| alloc | 1 | 0/1/0 | 3 | 1 | 10~16 |
| compliance | 1 | 0/1/0 | 3 | 1 | 10~16 |
| edu | 1 | 0/1/0 | 3 | 1 | 10~16 |
| pm | 1 | 0/1/0 | 3 | 1 | 10~16 |
| posrisk | 1 | 0/1/0 | 3 | 1 | 10~16 |
| ops | 2 | 2/0/0 | 2 | 1 | 10~16 |
| uxui | 2 | 2/0/0 | 2 | 1 | 10~16 |
| audit | 1 | 1/0/0 | 1 | 1 | 10~16 |
| maint | 1 | 1/0/0 | 1 | 1 | 10~16 |
| peer | 1 | 1/0/0 | 1 | 1 | 10~16 |
| quant | 1 | 1/0/0 | 1 | 1 | 10~16 |

합계(추정): 깨움 44회 ≈ 440~704만 토큰. S 만 있는 데스크 6곳(ops·uxui·audit·maint·peer·quant, 8건)을 정기 라운드에 얹으면 -6회(≈60~96만).

**받는 쪽 정정:** req-dev-516bf7e6·req-dev-cb19b1e0 은 장부 to=dev 지만 보드 owner=프론트(82d1acbd) — 표는 front 로 셈.

#### data (25)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-data-25c610af | L | 6종 중 백필 가능 2(DART·공매도) 먼저 |
| req-data-76cf9141 | L | 784ffc43 와 같은 공공 API 묶음(P0-1~7) |
| req-data-784ffc43 | L | 허브 — derivs·hf·verify·bonds·data-1a3f3978 이 기다림 |
| req-data-ecc8937e | L | 생존편향 포함 1999~ 이력 — 가능 여부 회신부터(S) |
| req-data-eee6de46 | L | ← req-dev-62a2f425 수집기와 한 묶음, KRX 키(사용자) 의존 |
| req-data-1a3f3978 | M | ① 784ffc43 에 통합 명시 — ②투자자별 경로 조사만 별도 |
| req-data-23bdae79 | M | ①은 784ffc43 회신으로 일부 반영 — ②③ 남음, 784ffc43 와 한 깨움 |
| req-data-3c64a717 | M | 20-F 분기 경로 조사 |
| req-data-5b659e78 | M | ① 완료(회신 10/24) — ②③ 공시 원문, 약속 10/29 |
| req-data-6c908141 | M | PMI·비료 월간 2종 |
| req-data-8309dae2 | M | 막힘: KRX_API_KEY 미등록(보드 user-krx-openapi-key, 사용자) |
| req-data-88dfbe9f | M | IBKR shortable 대안 탐침 |
| req-data-982cb414 | M | analyst_cmdty 자동 감지 |
| req-data-a555e088 | M | bonds_hist 2022 행 0 확인 — bonds 2022 Δy 가 기다림 |
| req-data-d16cfea5 | M | 토스 호출 한도 확인 |
| req-data-ebd5661d | M | live 루프 신규 파일 — 개발 잠금 확인 |
| req-data-14f05fa8 | S | RSS 약관 목록 |
| req-data-1fd3dc04 | S | 단일 출처 지정 완료(회신 10/25) — 토스 대조 1회 후 닫기, 기한 10/28 |
| req-data-26d5938d | S | realestate.py 실거래 연결로 일부 해소(784ffc43 회신) — R-ONE 주간만 확인 |
| req-data-2ff2a4e7 | S | 공개 자료 조사 회신 |
| req-data-6f17926c | S | public_reports kcmi 파서 수정(report_no 미처리 확인) |
| req-data-7ff634a5 | S | 지수 변경일 확인 |
| req-data-866790c9 | S | 거래 요건 출처·기준일 |
| req-data-c77cf2b8 | S | 일봉 완료(회신 10/24) — 괴리율(NAV 원천)만 남음 |
| req-data-cb6315c2 | S | 공공누리 4유형 게시 대조 — 784ffc43 공개 전 선행 |

#### dev (17)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-dev-0d73cae1 | L | 데이터 저장 위치 합의 필요 |
| req-dev-62a2f425 | L | ← req-data-eee6de46 와 한 묶음 |
| req-dev-7f441720 | L | STUDY handoff 남은 항목 3~4개 |
| req-dev-d026b1af | L | 치명 후속 — ④ slop_audit JSON 스캔은 반영됨(JSON_GLOBS), ①②③ 남음. req-pb-9e7fce79 가 기다림 |
| req-dev-1a14cbe5 | M | STUDY 측정 정상화 — 826c4bf0 묶음 |
| req-dev-4f89d244 | M | 1단계 완료(843ab877) — 국장 DART 잠정실적 남음 |
| req-dev-54eba83d | M | ① 완료·② btc.json 까지(회신 10/25) — briefing 연결·화면 남음, briefing 장중 수정 금지 |
| req-dev-826c4bf0 | M | STUDY apt 첫 응답 고정 — req-dev-1a14cbe5·req-edu-11644241 과 한 묶음 |
| req-dev-d08bcc86 | M | 자막·본문 수집(requirements 영향 확인) |
| req-dev-d1b2e934 | M | req-dev-228cac19 규격 흡수(오늘 중복 닫음) |
| req-dev-082223e8 | S | KR 지수 16:20 전 잠정 표시 |
| req-dev-4dcda5cb | S | duel 재채점 1건 |
| req-dev-56e317b9 | S | 문서 2줄 정정(:3·:24) — req-dev-2b62ee7b 흡수, 미정정 확인 |
| req-dev-808893e4 | S | peers_US 일별 누적 파일 |
| req-dev-838025ff | S | 일회성 탐침(10/21 밤 예정) — 실행 여부 확인, 안 했으면 폐기 판단 |
| req-dev-9445319c | S | ② 철회됨 — ① ponytail-fixes 보드 검수→완료만(req-audit-45c91678 done) |
| req-dev-dbd49e21 | S | calendar TENTATIVE 목록 |

#### pb (9)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-pb-1a630ea8 | M | rulebook 배선 — 규칙 변경이라 겸이 결재 경로 |
| req-pb-9e7fce79 | M | ① PB 규칙 추가 확인(pb-private CLAUDE.md) · ② 복기 pb.md 15행 확인 — ③④ 겸이 결정 대기(agreements 394행 🗳️) |
| req-pb-036d2f5b | S | 겸이 결재 — 11/15 안건과 묶기 제안 |
| req-pb-23606b98 | S | 비공개 원장 꼬리표 |
| req-pb-584233b1 | S | 비공개 작업 9건 상태 회신 |
| req-pb-65b39a04 | S | 비공개 복기·정정 |
| req-pb-8a75f2cf | S | 겸이 결재 1건(모의 사이즈 문구) — 71d9c381 ③ 흡수 |
| req-pb-97b70a69 | S | 11/15 결재 안건 |
| req-pb-ec64b316 | S | 겸이 확인 1줄 후 갱신 |

#### front (6)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-front-184a8da5 | L | 데이터 준비 완료(d5a79949) |
| req-dev-516bf7e6 | M | 보드상 프론트로 재배정(82d1acbd) — 받는 쪽 front 로 처리 |
| req-front-75d54530 | M | 데이터 계약 완료(dc03028c, schema 2) |
| req-front-b433cc36 | M | 부스팅(교육) |
| req-dev-cb19b1e0 | S | 보드상 프론트로 재배정 — 받는 쪽 front 로 처리 |
| req-front-4e7ee8ad | S | 위젯 1개 |

#### eval (6)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-eval-2a85c6e6 | M | 평행 문항 12개 출제(11/5) |
| req-eval-09b261a3 | S | 프론트 온보딩 채점 — 09b261a3·2ca20b5e②·bde23545 한 묶음 |
| req-eval-2ca20b5e | S | 반려 3건 재검수 + 프론트 퀴즈 키 |
| req-eval-b5a3938d | S | 트랙 J 17문항 검수 |
| req-eval-bde23545 | S | front-d1 키 검수 |
| req-eval-c1ea8066 | S | 리스크본부 퀴즈 12문항 검수 |

#### realestate (5)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-realestate-4b04eae0 | M | 데이터 쪽 반영 완료(회신 10/24) — 부동산 판단분 남음 |
| req-realestate-4b175353 | M | 비공개 참조 입력 |
| req-realestate-6beefa2a | M | 트랙 J 사실 검수 |
| req-realestate-8d77a6b9 | M | household-a213e261 과 같은 정정 |
| req-realestate-acdff38a | M | 경로 A/B/C 비교표 |

#### household (5)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-household-da7a8e45 | L | 30년 비교 모델(비공개) |
| req-household-5384bf04 | M | 비공개 입력 — pb-private household/ |
| req-household-a213e261 | M | realestate-8d77a6b9 와 같은 정정 |
| req-household-ee4dcf8d | M | 비공개 입력값 반영 |
| req-household-4c160bc3 | S | 원인 대조 완료(PB 10/25) — 표시 변경 2곳 남음 |

#### frm (4)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-frm-562adc9a | M | 60f6b60e 와 한 표 |
| req-frm-585cd67f | M | stress_loss semi vs semi_new 분류 불일치 — 규칙 아님, 계산 경로 확인 |
| req-frm-60f6b60e | M | 계획 회신(10/23) — 11/14 마감, 562adc9a 와 한 표(11/15 안건 A) |
| req-frm-66618199 | S | 경계 검토 회신 |

#### bonds (3)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-bonds-d3eab49e | M | ← req-data-784ffc43(채권시세 V2 수집) 후 |
| req-bonds-6a40b909 | S | policy_rates.json 검토 회신 |
| req-bonds-ebfaf9a6 | S | alloc 11/15 ISA 리뷰 입력 |

#### hf (3)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-hf-20777b29 | M | req-hf-ab25efa4 흡수 — 키 time_exit·thesis_stop·iv_review, 검증 10/30 주의 조건 |
| req-hf-e379cf37 | M | ← req-data-784ffc43 |
| req-hf-c7fd8c65 | S | hf_risk 고정 입력 테스트(tests/ 참조 0 확인) |

#### life (2)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-life-7e0577df | M | 비공개 인수인계 — 상태 미확인 |
| req-life-bc4747b3 | S | 지표 수신 확인 회신 |

#### behavior (2)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-behavior-2341259f | M | pick_gate 규칙 판단(판정만, 구현은 개발) |
| req-behavior-13eed225 | S | Odean 1998 Table 1 대조 1줄 |

#### derivs (2)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-derivs-c63f55a9 | L | ← req-data-784ffc43·req-data-1a3f3978, 설계만 |
| req-derivs-cd54b890 | M | ← req-data-784ffc43 |

#### ops (2)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-ops-1b60cbd5 | S | 2건 approval 판정 |
| req-ops-e6543186 | S | schedule_table 1행(trig_ 미기재 확인) |

#### uxui (2)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-uxui-2ca21d0b | S | 판단 1줄 |
| req-uxui-623edd60 | S | uxui.md 머리말 1줄 |

#### verify (2)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-verify-7829ae44 | M | SOX 상대수익률 재계산 |
| req-verify-cb391f74 | M | ← req-data-784ffc43 |

#### alloc (1)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-alloc-b3949ced | M | 부동산 J13·J14 근거, household·realestate 결과 참고 |

#### audit (1)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-audit-dc25d18e | S | 감사 10/24 §6 종결 추적표 갱신만 — req-ops-e6543186 과 같은 예약 |

#### compliance (1)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-compliance-39223a83 | M | 신입 온보딩 이수(실습 2·퀴즈) |

#### edu (1)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-edu-11644241 | M | 회신 3회(일정 ①10/26 ②10/27 ③10/28) — ①부터 |

#### macro (1)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-macro-1384f2aa | L | 총재 뷰 장부 신설 |

#### maint (1)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-maint-baec0edf | S | gas_deploy scriptId 대조 |

#### peer (1)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-peer-fb30b165 | S | 계속/폐기 회신 |

#### pm (1)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-pm-100484e2 | M | 11/07 측정 — 이 문서 숫자 재사용 |

#### posrisk (1)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-posrisk-1b10b792 | M | 신입 온보딩 이수 |

#### quant (1)
| id | 크기 | 상태·의존성 |
|---|---|---|
| req-quant-c3b0fbd0 | S | 사전등록 검수 회신 |

## 6. 화 10/27 23시 이후 풀가동 — 배치 순서 제안 (데스크당 1회 깨움에 몰아 처리)
원칙: ① 남을 막고 있는 허브 먼저 ② S 는 한 깨움에 쓸어 담기 ③ L 은 첫 깨움에 '가능 여부·설계'까지만, 구현은 2차 밤 ④ 비공개 입력이 필요한 건(내무·부동산 일부·PB)은 pb-private 세션에서.

| 웨이브 | 깨움 | 담을 요청 | 토큰(만, 추정) |
|---|---|---|---|
| 1 (23:00~) 허브·치명 | 데이터 #1 | req-data-cb6315c2(게시 가능 대조 선행) → req-data-784ffc43 · req-data-76cf9141 · req-data-23bdae79 · req-data-1a3f3978 | 10~16 |
| 1 | 개발 #1 | req-dev-d026b1af(치명 후속 ①②③) · req-dev-56e317b9 · req-dev-9445319c · req-dev-082223e8 · req-dev-4dcda5cb | 10~16 |
| 2 S 쓸기 | 데이터 #2 | S 8건(req-data-14f05fa8·1fd3dc04·26d5938d·2ff2a4e7·6f17926c·7ff634a5·866790c9·c77cf2b8) + req-data-a555e088 | 10~16 |
| 2 | 개발 #2 | req-dev-d1b2e934 · req-dev-dbd49e21 · req-dev-808893e4 · req-dev-838025ff · req-dev-4f89d244 | 10~16 |
| 2 | 평가 #1 | S 5건(프론트 온보딩 3건 한 묶음 + J 17문항 + 리스크본부 12문항) | 10~16 |
| 2 | 프론트 #1 | req-dev-cb19b1e0 · req-front-4e7ee8ad · req-front-75d54530 · req-dev-516bf7e6 | 10~16 |
| 3 데이터 산출 뒤 | 파생·HF·채권·검증·FRM 각 1 | req-derivs-cd54b890 / req-hf-20777b29·c7fd8c65·e379cf37 / bonds 3건 / verify 2건 / frm 4건(11/15 안건 A 표 한 번에) | 50~80 |
| 4 | 부동산·내무·교육·행동·LIFE 각 1 | realestate 5 · household 5(비공개 입력) · req-edu-11644241 · behavior 2 · life 2 | 50~80 |
| 결재 | PB(메인) → 겸이 1회 | req-pb-036d2f5b · 8a75f2cf · 97b70a69 · 1a630ea8 · 9e7fce79 ③④ + 폐기 후보 4건 — 결재 메시지 1통 | 깨움 없음 |
| 정기 라운드 | ops·uxui·audit·maint·peer·quant | S 8건 — 추가 깨움 없이 다음 정기 라운드에 | 0(추가분) |

- **1차 밤 합계: 깨움 16회 ≈ 160~256만 토큰** → 105건 중 약 70건(S 전부·M 대부분) 처리 목표 [추정].
- **2차 밤 이후(L 잔여 13건 중 구현분):** req-data-25c610af·ecc8937e·eee6de46(KRX 키 사용자 대기) · req-dev-0d73cae1·62a2f425·7f441720 · req-front-184a8da5 · req-household-da7a8e45 · req-macro-1384f2aa · req-derivs-c63f55a9 · 데이터 #3 (M 잔여 6건) — 깨움 약 12~15회 ≈ 120~240만.
- 외부 대기(우리 손 밖): req-data-8309dae2 ← 보드 user-krx-openapi-key(사용자). 화 11시 이후 착수로 이미 잡힌 건(784ffc43·76cf9141·982cb414·4e7ee8ad 등)은 11시 창에서 먼저 시작해도 같은 배치.

## 7. 다음
- 화 회의: 폐기 후보 4건 결재, §0 승격 시점 관찰(due 전 승격 6건) 확인 요청.
- PM: 웨이브 1·2 끝난 뒤 이 표에서 닫힌 id 를 지우고 남은 수를 req-pm-100484e2(11/07 충원 판정) 숫자로 재사용.

## 8. 10/26 2차 정리 (PM, 19:50~ KST)
> 지시: 겸이 10/26 "우선순위 낮고 chore한 거 묶어서 한 번에 해버리든가 기각해". 출발 = 열린 요청 108건(1차 정리 뒤 + 오늘 신규). 결재·규칙 변경·실계좌·개인 재무·보안/유출 관련은 기각 대상에서 제외(남김). 크기·깨움·토큰은 **PM 추정 [검증전]**.

**기각 12 · 처리 4 · 묶음 C 이관 5(+묶음 요청 1 신설) → 남은 88** (108 − 21 + 1).

| 구분 | id | 사유(1줄, 장부 회신과 같음) |
|---|---|---|
| 기각 | req-data-25c610af | L, 옵션·공매도·선물은 784ffc43·eee6de46·1a3f3978 로 대체 — 나머지는 범위 좁혀 새 요청 |
| 기각 | req-data-88dfbe9f | 소형주 숏 연구 — 실행 축 아님, 탐색 비용 큼 |
| 기각 | req-data-ecc8937e | 무료 원천 미확인 L — 생존편향 표기로 진행 |
| 기각 | req-data-d16cfea5 | 네이버 경로 작동 중, 전환 이득 작음 |
| 기각 | req-data-c77cf2b8 | 일봉·ATR 완료, 괴리율만 남음 — 관심목록 단계 |
| 기각 | req-data-3c64a717 | 20-F 무료 분기 경로 없음 — no_data 표기 유지 |
| 기각 | req-data-6c908141 | 외부 논객 채점용 PMI·비료 — 우선순위 낮음 |
| 기각(중복) | req-data-26d5938d | → req-data-76cf9141(R-ONE)·23bdae79(실거래) |
| 기각(중복) | req-data-a555e088 | → req-data-76cf9141 ECOS 국고 백필(2021-12~2022-12 먼저, 회신에 명시) |
| 기각 | req-dev-0d73cae1 | 잡주 1m 기록기 L — 연구 축 우선순위 낮음 |
| 기각(낡음) | req-dev-838025ff | 10/21 일회성 탐침, 실행 흔적·기다리는 쪽 없음 |
| 기각 | req-life-bc4747b3 | 수신 확인 회신 — 지표는 그대로 받음 |
| 처리 | req-dev-56e317b9 · req-ops-e6543186 · req-uxui-623edd60 · req-dev-9445319c | 커밋 e6fe1c30 (문서 2줄 정정·schedule_table 1행·uxui 머리말·보드 ponytail-fixes 완료) |
| 묶음 C | req-dev-082223e8 · 4dcda5cb · dbd49e21 · 808893e4 · req-hf-c7fd8c65 | → **req-dev-a3f3a6b4**(개발, 마감 10/30) 한 깨움 |

남긴 것(기각 안 함, 규칙상): req-data-2ff2a4e7·866790c9(실계좌 주문·거래 요건), PB·내무·부동산·LIFE 비공개 건, 결재(req-pb-db57c704·req-ops-1b60cbd5), 보안(req-dev-d026b1af·req-data-cb6315c2).
보드: '[요청 승격]' 중 요청이 닫힌 9건 완료(req-data-25c610af·88dfbe9f·d16cfea5·c77cf2b8 · req-dev-0d73cae1·838025ff · req-pb-036d2f5b·1a630ea8·8a75f2cf — 뒤 3건은 PB 결재로 닫힘) + ponytail-fixes → '[요청 승격]' 미완 21 → 12, P1 미완 47.

### 데스크별 남은 수 (88, 받는 쪽 = 보드 owner 기준 — req-dev-516bf7e6·cb19b1e0 은 front)
data 16 · dev 11(묶음 C 포함) · front 6 · frm 6 · eval 6 · pb 6 · realestate 5 · household 5 · bonds 3 · quant 3 · behavior 2 · derivs 2 · hf 2 · macro 2 · verify 2 · 1건씩: life·audit·compliance·edu·maint·ops·peer·pm·posrisk·uxui·scribe (11).

### 화 10/27 23시 배치 수정 (§6 대비)
- 데이터: 25 → 16건(L 5→3, M 11→7, S 9→6) — 부하 82 → 51점, 깨움 9 → 5. **데이터 #3(M 잔여) 삭제.** #2 는 S 6건(14f05fa8·1fd3dc04·2ff2a4e7·7ff634a5·866790c9·cb6315c2 중 cb6315c2 는 #1 선행) + ISA 입력 5b659e78·b83a7ef9.
- 개발: #1 = d026b1af(치명 후속) · 43d17d83(결재 구현 rulebook) · d1b2e934. #2 = **묶음 C(a3f3a6b4)** · 4f89d244.
- FRM: 4 → 6건(오늘 신규 2ff808c9 — 11/2 09:30 전 회신 희망, e18dcee7 — 화 23시 결재 구현) — 웨이브 3 FRM 깨움 1회에 6건.
- LIFE: 남은 건 비공개 인수인계 1건뿐 → 웨이브 4 LIFE 깨움 삭제, pb-private 세션(내무와 같이)으로.
- **1차 밤: 깨움 16 → 15회 ≈ 150~240만 토큰.** 2차 밤 이후 L 잔여 13 → 10건(25c610af·ecc8937e·0d73cae1 기각), 깨움 12~15 → 8~11회 ≈ 80~176만. 전체 추정 깨움 44 → 약 37회 [추정].
