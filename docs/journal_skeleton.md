# 일일 저널 뼈대 (`scripts/journal_skeleton.py`)

공개 저장소의 `reports/*` 만 읽어 그날의 **사실 줄**을 미리 채운 Markdown 뼈대를 만든다. 감정·대응 칸은 전부 `…` 로 비워 두고, 비공개 저널(pb-private)에서 사람이 채운다. 보유·수량·금액은 읽지도 쓰지도 않는다 — 출력에 금액 키나 `n,nnn,nnn원` 패턴이 섞이면 스크립트가 스스로 실패한다.

## 입력 (전부 공개)
| 파일 | 뽑는 것 |
|---|---|
| `reports/events.json` | 그날 이벤트(서킷·사이드카·연준 의장 발언·경보) 시각·제목 |
| `reports/decisions.json` | 그날 대결 항목의 나/나🔥/PB/PB🔥/규칙 픽(종목명·진입·청산 코드·제출 시각) + 주문표(kind=ticket: 판정·손익비·보유일) |
| `reports/archive/committee/_index.json` + 그날 회의 파일 | 세션·시각·신호등 라벨·판정·Δ(직전 회의 대비) 줄 |
| `reports/rebound.json` | 14:25 반등일 판정 (있으면 제목에 `· 반등일` 표시) |
| `reports/live.json` → `reports/daily_hist/_index.json` | 코스피·코스닥 종가·등락 (live 가 그날 CLOSE 가 아니면 일일 요약 헤드라인에서) |
| `reports/studies/*.json` | 그날 커밋(`git log --since/--until`, KST)으로 바뀐 `*grade` 키를 파일별 건수·등급 분포로 요약 |

## 출력 구조
```
# 매매 일기 — YYYY-MM-DD(요일) [· 반등일]
## 오늘의 장        종가 · 반등일 판정 · 이벤트 · 회의(세션별 라벨·판정·Δ) · 수급 … · 파생 …
## 오늘의 대결      항목별 픽 (금액 없음) · 주문표
## 마음의 타임라인  | 시각 | 마음 | 대응 | 결과 |  — 이벤트·픽 제출·판정·회의가 시각순으로 '결과' 칸에, 나머지는 …
## 패턴 메모        …
## 연구 등급 변경   파일별 요약 (없으면 '없음')
## 14:30 이후       체크리스트 (집행 여부 · 종가 확인 · 한 줄 회고)
```

## 사용
```bash
python scripts/journal_skeleton.py                        # 오늘(KST) → stdout
python scripts/journal_skeleton.py --date 2026-10-16      # 특정 날짜 → stdout
python scripts/journal_skeleton.py --date 2026-10-16 --out /path/to/2026-10-16.md
```
`--out` 은 파일이 **없을 때만** 쓴다. 이미 있으면 덮어쓰지 않고 기존 파일 ↔ 새 뼈대의 unified diff 를 참고용으로 출력한다(사람이 쓴 저널을 지우지 않기 위해).

### 비공개 쪽 16:00 명령 (PB 가 실행)
```bash
cd /home/user/market-screener && git pull -q origin main
python scripts/journal_skeleton.py --date $(TZ=Asia/Seoul date +%F) \
  --out /home/user/pb-private/journal/$(TZ=Asia/Seoul date +%F).md
```
- 파일이 없으면 뼈대가 생성된다 → 16:00 최종 보고 때 `…` 칸과 '14:30 이후' 체크리스트를 채운다.
- 파일이 이미 있으면(장중에 먼저 쓴 경우) diff 제안만 나온다 → 빠진 사실 줄(종가·회의 Δ·등급 변경)만 손으로 옮긴다.
- 공개 저장소에는 절대 `--out` 으로 쓰지 않는다. 출력은 pb-private 전용.

## 검사
```bash
python -m pytest -q tests/test_journal_skeleton.py
```
합성 입력으로 사실 줄 채움·감정 칸 공란·금액 미포함·기존 파일 보호를 확인한다.
