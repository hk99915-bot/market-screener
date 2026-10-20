# 토스 시세 수집 — 겸이 노트북(Windows) 세팅 가이드

작성 2026-10-20 · 개발 데스크 · 보드 `toss-md-pilot` · 코드 `screener/toss_md.py`, `tools/toss_md/` · 테스트 `tests/test_toss_md.py`

**한 줄 요약:** 노트북을 "시세만 받아 적는 기록원"으로 만든다. 주문은 미래에셋에서 하므로 토스로는 **절대 주문하지 않고**, 코드도 주문·계좌 길을 아예 막아 두었다.

> **꼭 지킬 것 3가지**
> 1. 키(client_id·client_secret)는 **채팅(Claude·텔레그램·카톡)에 붙여 넣지 않는다.** 노트북의 비밀 파일에만 적는다.
> 2. 수집기는 **이 노트북 1대에서만** 돌린다. 토스는 키 하나에 유효한 출입증(토큰)이 1장뿐이라, 다른 곳에서 새로 받으면 노트북 것이 바로 무효가 된다.
> 3. 수집한 파일(`toss_md_data` 폴더)은 **저장소에 올리지 않는다.** 약관(재배포)을 아직 확인 못 했다.

---

## 0단계 — 시작 전에 확인 (약관)
비유: 도서관 자료를 복사해 가도 되는지, 친구에게 나눠 줘도 되는지부터 확인한다.
- [ ] 토스증권 Open API **이용약관**에서 ① 받은 시세를 **다른 곳에 공개·재배포**해도 되는지 ② **자동 수집(프로그램으로 주기 호출)** 이 허용되는지 확인. → 결과를 PB에게 "허용/금지/불명확" 한 단어로만 알려 주기(약관 문장 통째 복사 불필요).
- 확인 전까지: 수집은 노트북 안에서만, 공개 저장소·화면에는 쓰지 않는다. (현재 상태: **미확인**)

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
   → `toss_md collect: ok=6 fail=0` 처럼 나오면 OK. (dry-run 결과는 `$HOME\toss_md_data\_dryrun\` 아래)
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

   # (가) 장중: 평일 09:00~15:50, 10분마다 — 지수 1분봉·매매대금·환율 (1분봉은 200개까지 받아 합치므로 10분 간격이면 빠짐 없음)
   $a1 = New-ScheduledTaskAction -Execute $py -Argument "tools\toss_md\collect.py --group intraday" -WorkingDirectory $repo
   $t1 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 09:00
   $t1.Repetition = (New-ScheduledTaskTrigger -Once -At 09:00 -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Hours 6 -Minutes 50)).Repetition
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

## ⑥ GitHub "self-hosted runner"로 붙이지 말 것
비유: 우리 저장소는 **공개 게시판**이다. 이 노트북을 GitHub 의 일꾼(self-hosted runner)으로 등록하면, 모르는 사람이 올린 글(PR)의 코드가 **이 노트북에서 실행**될 수 있다 — 그 코드는 서랍 속 키를 읽어 주문까지 낼 수 있다.
- 그래서 수집은 **작업 스케줄러로만** 돌리고, GitHub Actions 와 연결하지 않는다.
- 같은 이유로 토스 키를 **GitHub Secrets 에도 넣지 않는다**(수집 주체가 둘이 되고, IP도 안 맞는다).

## ⑦ 키가 샜다고 의심될 때 (바로 할 일)
비유: 출입카드를 잃어버리면 카드부터 정지시키고, 그다음 경위를 본다.
1. **즉시** 토스증권 WTS → Open API → 키 **폐기(삭제/재발급)**, 허용 IP 목록 **비우기**. [미확인, 확인 필요: WTS 에 키 폐기·IP 해제 기능이 실제로 있는지와 메뉴 위치 — 0단계 약관 확인 때 같이 확인]
   - 그 기능이 없으면: 토스증권 고객센터에 "Open API 키 정지" 요청.
2. 토스 앱 → 주문 내역·체결 내역에서 **내가 하지 않은 주문**이 있는지 확인(있으면 고객센터 신고).
3. 노트북에서 작업 끄기: `Disable-ScheduledTask toss_md_intraday; Disable-ScheduledTask toss_md_daily`
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
