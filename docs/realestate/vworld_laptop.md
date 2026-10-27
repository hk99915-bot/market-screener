# 브이월드 단지 좌표 — 노트북(국내 IP) 1회 실행법

작성 2026-10-27 · 개발 데스크 · 요청 `req-dev-dcd43e3b` · 코드 `screener/realestate_coords.py`(`main`) · 테스트 `tests/test_realestate_coords.py`

**한 줄 요약:** Actions(미국 IP)에서 브이월드가 끊김(10/26 10:45 `502 Bad Gateway`, 10:55 `RemoteDisconnected` — 해외·클라우드 IP 차단 가설, 미확인) → 국내 IP 노트북에서 좌표 캐시만 채워 올리고, 화면용 파일에 붙이는 일은 다음 Actions 부동산 실행이 캐시로 한다.

> **꼭 지킬 것**
> 1. 키는 **환경변수 `VWORLD_KEY`** 로만 넘긴다. 채팅·저장소·명령 인자·파일에 적지 않는다(코드가 인자로는 안 받음).
> 2. 커밋하는 파일은 **`reports/realestate_coords.json` 하나**. 폴리곤 원본은 저장·재배포하지 않는다(중심점만).

## 0. 준비 (토스 가이드 ②단계를 했으면 끝)
- Python 3.11+, 저장소 받기·`pip install -r requirements.txt` — `docs/toss_md_laptop_setup.md` ②단계와 같다.
- 브이월드 키 발급 때 등록한 **서비스 URL** 이 `https://hk99915-bot.github.io` 가 아니면 `VWORLD_DOMAIN` 도 같은 값으로 준다.

## 1. 남은 필지 확인 (호출 없음)
```powershell
git pull
python -m screener.realestate_coords --dry
```
- 출력 예: `캐시 0필지 · 남은 필지 3402 · Actions 연속 실패 기록 없음` (10/27 이 저장소 기준 — 1,500회씩 약 3일)

## 2. 실행 (PowerShell — 이 창에서만 키가 살아 있음)
```powershell
$env:VWORLD_KEY = Read-Host "VWORLD_KEY"      # 화면에 붙여 넣기만, 저장 안 됨
python -m screener.realestate_coords --max 1500
Remove-Item Env:VWORLD_KEY
```
- 한 번 상한 기본 1,500회(브이월드 일 한도 안쪽 — [확인 필요: 키별 일 한도 수치, 브이월드 마이페이지, 2026-11-03]). 남으면 **다음 날 같은 명령** — 캐시에 있는 필지는 건너뛰므로 이어받기 된다.
- 동작: 필지당 일시 오류(502·끊김·시간초과) 3회 재시도 → 그래도 실패면 그 필지만 건너뜀(다음 실행에 다시). 5필지 연속 건너뛰면 중단. 키·도메인·한도 오류(401·403·`INVALID_KEY`·`OVER_REQUEST_LIMIT`)는 즉시 중단.
- 끝 줄 JSON: `ok_calls`(성공) · `skipped`(건너뜀) · `error`. 종료 코드 1 = 성공 0건 + 오류.

## 3. 올리기
```powershell
git add reports/realestate_coords.json
git commit -m "realestate: 단지 좌표 캐시 (노트북)"
git pull --rebase; git push
```
- `reports/realestate_trades/` 는 바뀌지 않는다(노트북 실행은 캐시만). 다음 Actions 부동산 실행이 캐시 좌표를 단지 행에 붙인다(키 없이도).

## Actions 쪽 동작 (③ 낭비 방지)
- Actions 실행에서 '성공 0' 이 **2회 연속**이면 캐시 파일에 `actions_fail` 기록 → 그 뒤 **7일** 동안 Actions 는 브이월드 호출을 생략하고 캐시만 붙인다. 7일 뒤 1회 재시도.
- 노트북 실행이 1건이라도 성공하면 `actions_fail` 이 지워진다.
- 롤백: `git revert` (Actions 가 다시 매 실행 호출, 첫 오류에서 중단하는 예전 동작).
