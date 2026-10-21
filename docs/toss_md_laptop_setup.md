# 토스 시세 수집 — 겸이 노트북(Windows) 세팅 가이드

작성 2026-10-20 (10/21 ⑥ publish 추가) · 개발 데스크 · 보드 `toss-md-pilot`·`toss-md-publish` · 코드 `screener/toss_md.py`, `tools/toss_md/` · 테스트 `tests/test_toss_md.py`

**한 줄 요약:** 노트북을 "시세만 받아 적는 기록원"으로 만든다. 주문은 미래에셋에서 하므로 토스로는 **절대 주문하지 않고**, 코드도 주문·계좌 길을 아예 막아 두었다.

> **꼭 지킬 것 3가지**
> 1. 키(client_id·client_secret)는 **채팅(Claude·텔레그램·카톡)에 붙여 넣지 않는다.** 노트북의 비밀 파일에만 적는다.
> 2. 수집기는 **이 노트북 1대에서만** 돌린다. 토스는 키 하나에 유효한 출입증(토큰)이 1장뿐이라, 다른 곳에서 새로 받으면 노트북 것이 바로 무효가 된다.
> 3. 수집한 원본 파일(`toss_md_data` 폴더)은 **저장소에 올리지 않는다.** 공개는 ⑥ publish 가 만든 **요약 2개**(지수·환율·수급 합계·대조 괴리율)만, 전용 브랜치 `toss-live` 로.

---

## 0단계 — 시작 전에 확인 (약관)
비유: 도서관 자료를 복사해 가도 되는지, 친구에게 나눠 줘도 되는지부터 확인한다.
- [ ] 토스증권 Open API **이용약관**에서 ① 받은 시세를 **다른 곳에 공개·재배포**해도 되는지 ② **자동 수집(프로그램으로 주기 호출)** 이 허용되는지 확인. → 결과를 PB에게 "허용/금지/불명확" 한 단어로만 알려 주기(약관 문장 통째 복사 불필요).
- (현재 상태: **허용** — 10/20 23:5x 겸이 확인, 재배포·자동수집. 그래서 10/21부터 ⑥ publish 로 요약만 공개.)

## ① 토스 WTS에서 Open API 키 발급 + 허용 IP 등록
비유: 건물 출입카드(키)를 받고, "이 집 주소(IP)에서 오는 사람만 들여보내 줘"라고 경비실에 등록하는 단계.

1. **내 공인 IP 확인** — 공인 IP = 인터넷 바깥에서 보이는 우리 집 주소.
   - PowerShell 을 열고(시작 → "PowerShell" 검색):
     ```powershell
     (Invoke-RestMethod -Uri "https://api.ipify.org")
     ```
   - 나온 숫자(예: `123.45.67.89` 꼴)를 메모. **이 숫자도 채팅·저장소에 올리지 않는다.**
2. **고정 IP인지 확인** — 집 인터넷은 보통 "유동 IP"(가끔 바뀜)다.
   - 방법 A: 위 명령을 오늘·내일·공유기 재부팅 뒤에 다시 실행해 같은지 본다.
   - 방법 B: 인터넷 회사(통신사) 고객센터에 "고정 IP 서비스 가입 여부" 문의.
   - 바뀌는 IP라면: 바뀔 때마다 WTS에서 허용 IP를 새로 등록해야 하고, 그 사이 수집은 `403`(IP 거부)로 실패한다. heartbeat 파일의 `last_error` 에 `status=403` 이 보이면 이것부터 의심.
3. **토스증권 WTS(PC 웹)** 로그인 → 설정 → **Open API** → 키 발급. 화면에 나오는 `client_id`, `client_secret` 은 바로 ③의 비밀 파일에 적는다(메모장 임시 저장·캡처 금지).
4. 같은 화면 **허용 IP 관리** 에 1번의 공인 IP 하나만 등록.
   - 메뉴 이름·위치는 PB가 받은 스펙 요약 기준이다. 실제 화면과 다르면 PB에게 메뉴 이름만 알려 주기.

## ② Python 설치 + 저장소 받기
비유: 기록원이 쓸 공책(Python)과 업무 지침서(저장소)를 책상에 올려 둔다.

1. **Python 3.11 이상** 설치 — python.org 의 Windows 설치 파일 실행, 첫 화면에서 **"Add python.exe to PATH" 체크** 후 Install.
   - 확인: PowerShell 에서 `python --version` → `Python 3.11.x` 이상이면 OK.
2. **Git** 설치(git-scm.com, 기본값 그대로 Next) 후:
   ```powershell
   cd $HOME
   git clone https://github.com/hk99915-bot/market-screener.git
   cd market-screener
   python -m pip install --user requests tzdata
   ```
   - 수집기는 `requests` 와 `tzdata`(Windows 에는 시간대 DB 가 없어 필요) 만 쓴다(전체 requirements 설치 불필요). `tzdata` 가 없어도 수집기는 +09:00 고정으로 돌지만 대조(crosscheck)는 저장소 휴장 표를 읽느라 `tzdata` 가 꼭 필요하다.

## ③ 비밀 파일(env) 만들기 + 권한 잠그기
비유: 출입카드를 **잠긴 서랍**에 넣는다. 서랍 열쇠는 나(현재 Windows 사용자)만 가진다.
용어: env 파일 = 키를 적어 두는 텍스트 파일, 권한(ACL) = 누가 그 파일을 열 수 있는지 목록.

1. 폴더와 파일 만들기 (PowerShell):
   ```powershell
   New-Item -ItemType Directory -Force "$HOME\.config\toss_md" | Out-Null
   notepad "$HOME\.config\toss_md\env"
   ```
   메모장이 뜨면(새 파일 만들기 → 예) 아래 두 줄을 **직접 입력**하고 저장:
   ```
   TOSS_MD_CLIENT_ID=여기에_client_id
   TOSS_MD_CLIENT_SECRET=여기에_client_secret
   ```
   - 메모장이 `env.txt` 로 저장하지 않게, 저장 대화상자에서 "파일 형식: 모든 파일"을 고르거나 아래 3번에서 이름을 확인한다.
2. **권한 잠그기 (icacls)** — "상속 끊기 + 나만 전체 권한":
   ```powershell
   $f = "$HOME\.config\toss_md\env"
   icacls $f /inheritance:r /grant:r "$($env:USERNAME):F"
   icacls $f
   ```
   - 마지막 줄 출력에 **내 계정 이름 한 줄만** 있어야 한다. `Everyone`, `BUILTIN\Users`, `Authenticated Users` 가 보이면 수집기가 **실행을 거부**한다(일부러 그렇게 만들었다).
3. 파일 이름 확인: `Get-ChildItem "$HOME\.config\toss_md"` → `env` (확장자 없음)여야 한다. `env.txt` 면 `Rename-Item "$HOME\.config\toss_md\env.txt" env` 후 2번 다시.
- 이 파일은 저장소 폴더(`market-screener`) **밖**에 있어야 한다. 저장소 안에 두면 수집기가 거부한다.
- 토큰(24시간 출입증)은 수집기가 같은 폴더 `token.json` 에 저장하고 같은 방식으로 잠근다.
- **절대 하지 말 것:** 키를 채팅·이메일·메모 앱·스크린샷으로 옮기기, 저장소의 `.env` 에 적기.

## ⑤ 먼저 시험 실행 (dry-run → 실제 1회)
비유: 리허설(가짜 자료) 한 번, 그다음 진짜 한 번.

1. **dry-run** (인터넷·키 없이, 저장소에 든 가짜 자료로 전 과정 점검):
   ```powershell
   cd $HOME\market-screener
   python tools\toss_md\collect.py --group all --dry-run
   python tools\toss_md\crosscheck.py --dry-run --date 2026-10-20
   ```
   → `toss_md collect: ok=8 fail=0` 처럼 나오면 OK. (dry-run 결과는 `$HOME\toss_md_data\_dryrun\` 아래)
2. **실제 1회** (평일 장중이면 좋다):
   ```powershell
   python tools\toss_md\collect.py --group all
   Get-Content "$HOME\toss_md_data\heartbeat.json"
   ```
   - `fail=0`, heartbeat 의 `last_success` 가 방금 시각이면 성공.
   - 실패하면 화면엔 `status=… code=…` 만 나온다(응답 내용은 일부러 안 보여 준다). **이 두 값만** PB에게 전달.
     - `status=403` → 허용 IP 문제(①-2·①-4) · `status=401` → 키 오타 또는 다른 곳에서 토큰을 새로 받음 · `status=404/400` → 경로 문제(개발 데스크가 고침, 아래 참고) · `status=429` → 너무 자주 호출(잠시 뒤 자동 재시도).
   - 경로는 OpenAPI 원문(v1.2.24)과 대조해 맞춰 두었다(10/20). 그래도 404/400 이면 status·code 만 PB에 전달 → 개발 데스크가 `tools/toss_md/collect.py` 의 `PILOT` 표를 고친다.
3. 저녁(16시 이후)에 대조:
   ```powershell
   git pull
   python tools\toss_md\crosscheck.py
   ```
   → 항목별 `[ok]/[breach]/[no_data]` 와 괴리율만 나온다. 이 요약 줄을 PB에게 전달(숫자는 괴리율뿐이라 공유해도 됨).

## ④ 자동 실행 등록 (작업 스케줄러) + 절전 해제
비유: 기록원에게 "평일 장중엔 10분마다, 아침·저녁엔 하루 한 번" 근무표를 준다. 노트북이 잠들면 기록원도 잠드니 절전도 끈다.
(⑤ 시험 실행이 성공한 **다음에** 등록한다.)

1. **Python 경로 확인:** `(Get-Command python).Source` → 예: `C:\Users\<나>\AppData\Local\Programs\Python\Python312\python.exe`. 아래 `$py` 에 넣는다.
2. **작업 등록** (PowerShell, 관리자 권한 불필요 — 내 계정으로 로그인해 있을 때 실행):
   ```powershell
   $py   = (Get-Command python).Source
   $repo = "$HOME\market-screener"

   # (가) 장중: 평일 08:00~20:00, 10분마다 — NXT 프리마켓(08:00)·KRX 정규장·시간외·NXT 애프터마켓(~20:00) 포함 (10/21 겸이 요청). 지수·투자자 매매대금은 KRX 정규장에만 움직이고, 시간외·NXT 구간은 환율·종목 시세(추가 시) 몫
   $a1 = New-ScheduledTaskAction -Execute $py -Argument "tools\toss_md\collect.py --group intraday" -WorkingDirectory $repo
   $t1 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 08:00
   $t1.Repetition = (New-ScheduledTaskTrigger -Once -At 08:00 -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Hours 12)).Repetition
   $s  = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
   Register-ScheduledTask -TaskName "toss_md_intraday" -Action $a1 -Trigger $t1 -Settings $s

   # (나) 하루 2번: 08:30(휴장 달력·종목 목록) · 18:30(매매대금 확정치 + 대조)
   $a2 = New-ScheduledTaskAction -Execute $py -Argument "tools\toss_md\collect.py --group all --stocks-all" -WorkingDirectory $repo
   $t2 = @((New-ScheduledTaskTrigger -Daily -At 08:30), (New-ScheduledTaskTrigger -Daily -At 18:30))
   Register-ScheduledTask -TaskName "toss_md_daily" -Action $a2 -Trigger $t2 -Settings $s
   ```
   - 확인: `Get-ScheduledTask toss_md_* | Get-ScheduledTaskInfo` → `LastTaskResult` 가 `0` 이면 성공(1 = 일부 실패, heartbeat 확인).
   - 끄기: `Disable-ScheduledTask toss_md_intraday` · 지우기: `Unregister-ScheduledTask toss_md_intraday -Confirm:$false`
   - `MultipleInstances IgnoreNew` + 수집기 자체 잠금(`collector.lock`) 덕분에 두 개가 겹쳐 돌지 않는다.
3. **절전 해제** (전원 연결 상태 기준):
   ```powershell
   powercfg /change standby-timeout-ac 0
   powercfg /change hibernate-timeout-ac 0
   ```
   - 덮개(뚜껑)를 닫아도 안 자게: 제어판 → 전원 옵션 → "덮개를 닫으면" → 전원 사용 시 **아무것도 안 함**.
   - Windows 업데이트 재부팅 뒤에도 작업은 남지만, **로그인해야** 돈다(위 등록은 "로그인했을 때만" 방식 — 비밀번호를 작업에 저장하지 않으려고). 재부팅 뒤엔 한 번 로그인만 해 두기.
4. **살아 있는지 보는 법:** `Get-Content "$HOME\toss_md_data\heartbeat.json"` 의 `last_success` 가 장중 10분 이내면 정상.

## ⑥ publish 켜기 — 터미널(Pages) 지수·장중 차트·환율·수급에 토스 연결 (10/21)
비유: 기록원이 공책(원본)은 책상 서랍에 두고, **요약 한 장**만 게시판 옆 전용 칸(브랜치 `toss-live`)에 붙인다. 터미널은 그 칸을 읽고, 요약이 늦으면 예전 출처(네이버·야후)를 보여 준다.
용어: 브랜치 = 저장소 안의 별도 칸. `toss-live` 에는 `live.json`·`crosscheck.json` 두 파일만 있고, main(본 게시판)에는 커밋하지 않는다.

1. **먼저 확인 (한 번만):**
   ```powershell
   cd $HOME\market-screener
   git pull
   python tools\toss_md\publish.py --dry-run
   ```
   → `toss_md publish: dry_run (...)` 이면 OK. 미리보기는 `$HOME\toss_md_data\_dryrun\publish_preview\live.json`.
2. **작업 스케줄러 인자에 `--publish` 추가** — 같은 이름으로 다시 등록(`-Force` 가 기존 것을 덮는다):
   ```powershell
   $py   = (Get-Command python).Source
   $repo = "$HOME\market-screener"
   $s  = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

   # (가) 장중 10분마다 수집 + publish (바뀐 게 없으면 커밋 안 함)
   $a1 = New-ScheduledTaskAction -Execute $py -Argument "tools\toss_md\collect.py --group intraday --publish" -WorkingDirectory $repo
   $t1 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 08:00
   $t1.Repetition = (New-ScheduledTaskTrigger -Once -At 08:00 -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Hours 12)).Repetition
   Register-ScheduledTask -TaskName "toss_md_intraday" -Action $a1 -Trigger $t1 -Settings $s -Force

   # (나) 08:30·18:30 달력·종목 목록 + publish (18:30 회차가 그날 대조(crosscheck)도 계산해 올린다)
   $a2 = New-ScheduledTaskAction -Execute $py -Argument "tools\toss_md\collect.py --group all --stocks-all --publish" -WorkingDirectory $repo
   $t2 = @((New-ScheduledTaskTrigger -Daily -At 08:30), (New-ScheduledTaskTrigger -Daily -At 18:30))
   Register-ScheduledTask -TaskName "toss_md_daily" -Action $a2 -Trigger $t2 -Settings $s -Force
   ```
   - 간격을 두고 싶으면 인자 끝에 `--min-interval 30` (분). 기본 0 = 수집 회차마다(변화 있을 때만).
3. **첫 push 때 GitHub 로그인 1회:** 처음 publish 가 돌 때 Git Credential Manager 가 **브라우저 로그인 창**을 띄운다(작업 스케줄러 실행 중엔 창을 못 띄울 수 있어 아래처럼 손으로 1회):
   ```powershell
   cd $HOME\market-screener
   python tools\toss_md\collect.py --group intraday --publish
   ```
   → 브라우저에서 GitHub 로그인·승인 → 다음부터는 저장된 자격 증명으로 자동. 화면에 `toss_md publish: pushed (...)` 가 나오면 끝.
   - **노트북 git 이름·이메일 설정은 필요 없다.** 스크립트가 커밋마다 봇 신원(`toss-md <toss-md-bot@users.noreply.github.com>`)을 쓴다 — 겸이 개인 이메일이 공개 이력에 남지 않는다.
   - 커밋은 작업 폴더(main)를 건드리지 않는다. 평소처럼 `git pull` 해도 충돌 없음.
4. **살아 있는지:** `Get-Content "$HOME\toss_md_data\heartbeat.json"` 의
   - `publish.status` = `pushed`(올림) / `skipped:no_change`(바뀐 것 없음, 정상) / `fail`(아래 `publish.error` 한 줄만 PB 에 전달 — 다음 회차에 자동 재시도, `pending: true`).
   - `rate_limit` = 그룹별 남은 호출 수(`remaining`) — 0 에 가까우면 PB 에 알리기.
   - 터미널 MARKET › KR 의 **TOSS LIVE** 패널에 `토스 · n분 전` 배지가 보이면 연결 완료. 노트북이 멈추면 20분 뒤 네이버/야후로 자동 폴백, 상단 신선도 배지에 `toss_md` 가 뜬다.
5. **파서 확인(첫 실데이터 1회):** `python tools\toss_md\publish.py --shape` → 파일별 **키 이름만**(값 없음) 출력. 수급·국채가 화면에 `—` 로 비면 이 출력을 PB 에 그대로 전달(개발이 키 이름을 맞춘다).

### ⑥-3 미장(프리·데이·정규·애프터)까지 — 작업 하나로 합치기 (10/21 01시, 겸이 "미장데이터 지금부터" · "프리장 데이장도")
비유: 기록원을 국장 담당·미장 담당 두 명 두면 출입증(잠금)이 하나라 서로 부딪힌다 → **한 명이 10분마다 깨어나서, 지금 열린 시장만** 적는다.
- `toss_md_live` = 평일 08:00 시작 · 10분 간격 · **24시간 지속**(다음날 08:00까지). 인자 `--group intraday,us --publish`.
  - 국장(intraday): 거래일 08:00~20:00 KST 에만 수집. 미장(us): 토스 4세션(데이 → 프리 → 정규 → 애프터) 안에서만. 세션 밖이면 그 그룹은 `skipped` 로 건너뛴다.
  - 세션 판정 = 수집해 둔 토스 휴장 달력의 세션 시각(있으면) → 없으면 미 동부시간 기준 "전날 20:00 ~ 당일 18:00 ET"(서머타임 기간 KST 09:00~다음날 07:00, **11/2부터 10:00~08:00** 자동).
  - 24시간인 이유: 겨울(서머타임 해제 뒤)엔 애프터가 08:00 KST 에 끝난다. 23시간 10분이면 07:10~08:00 을 놓친다. 금요일 트리거가 토요일 08:00 까지 이어져 **금요일 밤 미장·토요일 새벽 애프터도 커버**된다.
  - 한 회차 호출 수: 국장 6 + 미장 8 = **14회** + publish(git fetch·push). 보통 1분 안. 429(호출 과다)면 호출마다 최대 3회·60초 대기라 최악엔 몇 분 → 실행 제한을 **10분**으로.
- `toss_md_sectors` = 매일 07:20, 토스 섹터 계층 + 섹터별 종목(KR·US) 1회. 호출 수 = 1 + 2 × 말단 섹터 수(호출 사이 0.5초). 30분 제한.
- `toss_md_daily`(08:30·18:30 달력·종목 목록)는 그대로. 겹치면 뒤에 온 쪽이 최대 4분 기다린다.
- (10/21 01:4x 수정) 섹터 수집은 **30호출마다 잠금을 놓고 3초 쉰다** → 섹터를 받는 동안에도 실시간 작업이 끼어든다. 한 실행 25분 상한, 못 끝내면 `sectors_partial.json` 에 진행분을 두고 다음 실행이 이어 받는다.
  - 예전 코드로 이미 돌고 있는 섹터 수집이 있으면 끝날 때까지 실시간 작업이 막힌다 → `Stop-ScheduledTask toss_md_sectors`(또는 그 창 닫기) 후 `git pull`, 그리고 `python tools\toss_md\collect.py --group sectors --publish` 다시 실행(받은 만큼은 이어 받지 못하고 처음부터 — 예전 코드는 진행분을 안 남김).
- 일봉(상단 지표 팝업 차트용, 10/21): `toss_md_sectors`(07:20)가 지수·국채 8 + 미장 ETF 7 = 15키를 키당 최대 3호출(200봉씩, ≤520봉)로 백필 → `toss_md_data\daily_bars\`. 실시간 작업은 오늘 봉만(국장 창 KOSPI·KOSDAQ 2회, 미장 창 SPY·QQQ·DIA·IWM·SOXX 5회). 공개는 toss-live 의 `daily_bars.json`(과거 — 07:20 에만 갱신, 하루 1커밋)·`daily_today.json`(그 뒤 봉, 10분).
- 국장 ETF·종목 현재가: 실시간 작업이 회차마다 `/prices` 1회(지표·ISA 코어·섹터 ETF 13개 + 운용회의 아이디어 + 시총 순, 200개)를 더 부른다 → 회차당 국장 7(+오늘 일봉 2) + 미장 8(+오늘 일봉 5) = 최대 22회.

```powershell
cd $HOME\market-screener
git pull
$py   = (Get-Command python).Source
$repo = "$HOME\market-screener"

# 0) 예전 국장 전용 작업은 지운다 (이게 남아 있으면 잠금이 부딪힌다)
Unregister-ScheduledTask -TaskName "toss_md_intraday" -Confirm:$false -ErrorAction SilentlyContinue

# 1) 국장+미장 한 작업: 평일 08:00 시작, 10분마다, 24시간
$s1 = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$a1 = New-ScheduledTaskAction -Execute $py -Argument "tools\toss_md\collect.py --group intraday,us --publish" -WorkingDirectory $repo
$t1 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 08:00
$t1.Repetition = (New-ScheduledTaskTrigger -Once -At 08:00 -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Hours 24)).Repetition
Register-ScheduledTask -TaskName "toss_md_live" -Action $a1 -Trigger $t1 -Settings $s1 -Force

# 2) 토스 섹터: 매일 07:20 (실시간 작업이 거의 쉬는 시각)
$s2 = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
$a2 = New-ScheduledTaskAction -Execute $py -Argument "tools\toss_md\collect.py --group sectors --publish" -WorkingDirectory $repo
Register-ScheduledTask -TaskName "toss_md_sectors" -Action $a2 -Trigger (New-ScheduledTaskTrigger -Daily -At 07:20) -Settings $s2 -Force

# 3) 지금 바로 1회 (점검): 미리보기 → 실제 1회 → 섹터 1회
python tools\toss_md\collect.py --group intraday,us --dry-run --no-gate
python tools\toss_md\collect.py --group intraday,us --publish
python tools\toss_md\collect.py --group sectors --publish
Start-ScheduledTask -TaskName "toss_md_live"
```
- 결과 한 줄 예: `toss_md collect: ok=8 fail=0 skipped={'intraday': 'fallback'} → …` (밤엔 국장이 쉬므로 정상).
- 미장 값 확인: 터미널 MARKET › US 의 **TOSS LIVE US** 패널(배지 `토스 · n분 전`). 비거나 `fail` 이면 `python tools\toss_md\publish.py --shape` 출력(키 이름만)을 PB 에 전달 — 미장 종목 캔들 파라미터 이름(symbol)·랭킹 응답 꼴은 [추정]이라 첫 실행으로 맞춘다.

## ⑦ GitHub "self-hosted runner"로 붙이지 말 것
비유: 우리 저장소는 **공개 게시판**이다. 이 노트북을 GitHub 의 일꾼(self-hosted runner)으로 등록하면, 모르는 사람이 올린 글(PR)의 코드가 **이 노트북에서 실행**될 수 있다 — 그 코드는 서랍 속 키를 읽어 주문까지 낼 수 있다.
- 그래서 수집은 **작업 스케줄러로만** 돌리고, GitHub Actions 와 연결하지 않는다.
- 같은 이유로 토스 키를 **GitHub Secrets 에도 넣지 않는다**(수집 주체가 둘이 되고, IP도 안 맞는다).

## ⑧ 정시 dispatcher — GAS 예약기 이중화 (10/21, 겸이 "지금 나온 이야기 다 ㄱㄱ")
비유: 알람시계(GAS)가 하나뿐이라 10/21 아침 08:40·08:50 에 안 울렸다 → 노트북에 **두 번째 알람시계**를 둔다. 둘 다 울려도 일은 한 번만 한다.
- 하는 일: 2분마다 `apps-script/Scheduler.gs` 시간표(단일 출처 — 표를 따로 두지 않음)를 읽어, 지금이 슬롯 **예정 +2~10분**이고 GAS 가 아직 안 보냈으면 GitHub 에 그 워크플로 실행 요청(workflow_dispatch) 1번.
- 둘 다 보내면: `scripts/slot_guard.py` 가 **먼저 만들어진 실행만** 돌리고 뒤엣것은 건너뛴다(테스트 `test_double_dispatch_gas_and_laptop_first_wins`).
- 하트비트: 매 실행 `~\toss_md_data\dispatcher.json` → 토스 publish 가 `live.json` 의 `dispatcher_heartbeat` 로 공개 → 장중 30분마다 `heartbeat.yml` 이 "슬롯 +20분인데 실행 요청 0건"이면 텔레그램 즉시 1통.
- 쓰는 권한: 이 저장소의 **Actions 만**(실행 요청·실행 목록). 계좌·주문·토스 키와 무관. 토큰은 화면·로그에 안 찍힌다(상태 코드만).

### ⑧-1 GitHub 토큰 만들기 (5분, 채팅으로 보내지 않는다)
1. github.com → 오른쪽 위 사진 → **Settings** → 맨 아래 **Developer settings** → **Personal access tokens → Fine-grained tokens** → **Generate new token**.
2. Token name `laptop-dispatch` · Expiration **90일**(만료일을 달력에 적기) · Resource owner `hk99915-bot`.
3. Repository access: **Only select repositories → market-screener** 하나만.
4. Permissions → Repository permissions → **Actions: Read and write** 하나만(나머지는 No access 그대로).
5. Generate → 나온 `github_pat_…` 값을 **복사만** 해 둔다(다음 단계에서 메모장에 바로 붙여넣기).

### ⑧-2 비밀 파일 + 작업 등록 (PowerShell)
```powershell
cd $HOME\market-screener
git pull
New-Item -ItemType Directory -Force "$HOME\.config\gh_dispatch" | Out-Null
notepad "$HOME\.config\gh_dispatch\env"
#   메모장에 한 줄:  GH_DISPATCH_TOKEN=github_pat_여기에붙여넣기   → 저장(파일 형식: 모든 파일, 이름 env)
$f = "$HOME\.config\gh_dispatch\env"
icacls $f /inheritance:r /grant:r "$($env:USERNAME):F"
icacls $f                      # 내 계정 한 줄만 보여야 한다 (넓으면 dispatcher 가 실행 거부 — ③과 같은 규칙)

# 점검: 지금 보낼 슬롯만 출력 (토큰 안 씀)
python tools\dispatch\dispatch.py --dry-run --now 2026-10-22T08:52     # → "[dry-run] 보낼 슬롯 …08:50|briefing.yml|premarket_kr"

# 등록: 매일 00:00 시작 · 2분마다 · 24시간 (주말 02:00 backfill·03:30 fin, 화~토 새벽 미장 슬롯 포함)
$py = (Get-Command python).Source
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
$a = New-ScheduledTaskAction -Execute $py -Argument "tools\dispatch\dispatch.py" -WorkingDirectory "$HOME\market-screener"
$t = New-ScheduledTaskTrigger -Daily -At 00:00
$t.Repetition = (New-ScheduledTaskTrigger -Once -At 00:00 -RepetitionInterval (New-TimeSpan -Minutes 2) -RepetitionDuration (New-TimeSpan -Hours 24)).Repetition
Register-ScheduledTask -TaskName "gh_dispatch" -Action $a -Trigger $t -Settings $s -Force
Start-ScheduledTask -TaskName "gh_dispatch"
Get-Content "$HOME\toss_md_data\dispatcher.json"     # last_run 이 방금 시각이면 OK (last_error null)
```
- 시간표가 바뀌면 노트북은 `git pull` 만(표는 Scheduler.gs 한 곳).
- 토큰 만료·의심 시: GitHub 에서 토큰 **Revoke** → `Disable-ScheduledTask gh_dispatch` → 새 토큰으로 ⑧-1부터. 그동안은 GAS + cron 대기(+12분)가 돈다.

## ⑨ 키가 샜다고 의심될 때 (바로 할 일)
비유: 출입카드를 잃어버리면 카드부터 정지시키고, 그다음 경위를 본다.
1. **즉시** 토스증권 WTS → Open API → 키 **폐기(삭제/재발급)**, 허용 IP 목록 **비우기**. [미확인, 확인 필요: WTS 에 키 폐기·IP 해제 기능이 실제로 있는지와 메뉴 위치 — 0단계 약관 확인 때 같이 확인]
   - 그 기능이 없으면: 토스증권 고객센터에 "Open API 키 정지" 요청.
2. 토스 앱 → 주문 내역·체결 내역에서 **내가 하지 않은 주문**이 있는지 확인(있으면 고객센터 신고).
3. 노트북에서 작업 끄기: `Disable-ScheduledTask toss_md_live; Disable-ScheduledTask toss_md_daily; Disable-ScheduledTask toss_md_sectors`
4. `$HOME\.config\toss_md\token.json` 삭제, 새 키를 받으면 ③부터 다시.
5. PB에게 "토스 키 폐기함, 시각 hh:mm" 만 알리기(키 값은 보내지 않는다).

## 우리 코드가 막아 둔 것 (참고)
| 막는 것 | 어떻게 | 확인하는 테스트 |
|---|---|---|
| 주문·계좌 호출 | 주소에 orders·accounts·holdings 등이 들어가면 **보내기 전에** 오류 | `test_forbidden_paths_raise_before_network` |
| GET 아닌 요청 | 토큰 발급 1곳 빼고 전부 거부 | `test_non_get_methods_refused` |
| 계좌 헤더 | 계좌 지정 헤더가 있으면 거부 | `test_account_header_refused` |
| 키 파일이 넓게 열림 | icacls 출력에 Everyone·Users 가 있으면 실행 거부 | `test_windows_acl_check` |
| 응답 내용이 로그에 남음 | 오류는 상태·code 만 | `test_error_body_not_logged` |
| 수집 파일이 저장소로 | 출력 폴더가 저장소 안이면 거부 | `test_collect_refuses_repo_output` |
| 두 대가 동시에 수집 | 잠금 파일 | `test_lock_blocks_second_collector` |
| 공개 요약에 호가·계좌·토큰·매수환율 | 금지 키가 있으면 publish 전에 오류 | `test_public_files_have_no_forbidden_fields` |
| 강제 push·이력 재작성 | 부모 있는 일반 커밋 + 일반 push 만 | `test_git_publish_branch_normal_push` |
