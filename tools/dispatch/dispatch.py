"""노트북 정시 dispatcher — GAS 예약기(apps-script/Scheduler.gs)의 이중화 (10/21 A1, 겸이 "지금 나온 이야기 다 ㄱㄱ").

10/21 08:40·08:50 GAS 슬롯이 하나도 dispatch 되지 않음(GAS 예약기 정지) → 같은 시간표를 노트북 작업 스케줄러가 2분마다 확인해
'지금 슬롯 창이면 workflow_dispatch'. 시간표 단일 출처 = Scheduler.gs SCHEDULE(scripts/slot_guard.parse_gas 로 읽음 — 표를 두 벌 두지 않음).

중복: GAS 가 이미 보냈으면(같은 키·슬롯 dispatch run 존재) 보내지 않는다. 동시에 보내도 slot_guard.earlier_dispatch 가 먼저 만든 run 만 실행.
보안: GitHub REST 의 workflow dispatch·run 목록 두 경로만, 이 저장소만. 토큰은 저장소 밖 env 파일(권한 검사 = 토스 키와 같은
      screener.toss_md.check_private_file) · 출력·예외에 토큰·응답 본문 없음(상태 코드만). 계좌·주문 경로 없음.
하트비트: 매 실행 ~/toss_md_data/dispatcher.json {last_run, last_dispatch, last_error} → toss_md publish 가 live.json
      'dispatcher_heartbeat' 로 공개 → scripts/watchdog.py --executor 가 20분 무소식 감지.

  python tools/dispatch/dispatch.py            # 작업 스케줄러 (docs/toss_md_laptop_setup.md ⑧)
  python tools/dispatch/dispatch.py --dry-run  # 지금 보낼 슬롯만 출력 (토큰 불필요)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import slot_guard as g  # noqa: E402
from screener.toss_md import _parse_env, check_private_file  # noqa: E402

REPO = "hk99915-bot/market-screener"
API = "https://api.github.com"
KST = timezone(timedelta(hours=9))
CONFIG = Path(os.environ.get("GH_DISPATCH_CONFIG_DIR", Path.home() / ".config" / "gh_dispatch"))
DATA = Path(os.environ.get("TOSS_MD_DATA", Path.home() / "toss_md_data"))
LEAD_MIN = 2   # GAS(5분 tick)가 주 실행 주체 — 노트북은 예정 +2분부터 보내 GAS 와 경합을 줄인다 (창 끝은 GAS 와 같은 WINDOW_MIN)


def load_token(cfg_dir: Path = CONFIG) -> str:
    tok = os.environ.get("GH_DISPATCH_TOKEN", "")
    f = cfg_dir / "env"
    if not tok and f.exists():
        check_private_file(f)
        tok = _parse_env(f.read_text(encoding="utf-8")).get("GH_DISPATCH_TOKEN", "")
    if not tok:
        raise RuntimeError("토큰 없음: ~/.config/gh_dispatch/env 에 GH_DISPATCH_TOKEN= (설정 가이드 ⑧)")
    return tok


def due(gas: dict, now_kst: datetime, done: set[str]) -> list[dict]:
    """지금 [예정+LEAD, 예정+WINDOW) 안이고 오늘 아직 안 보낸 슬롯."""
    nm, dow, day = now_kst.hour * 60 + now_kst.minute, now_kst.isoweekday() % 7, now_kst.date().isoformat()
    out = []
    for s in gas["slots"]:
        if dow in s["days"] and s["min"] + LEAD_MIN <= nm < s["min"] + gas["window_min"] and slot_id(s, day) not in done:
            out.append(s)
    return out


def slot_id(s: dict, day: str) -> str:
    return f"{day}|{s['time']}|{s['wf']}|{g.gas_key(s)}"


def _req(method: str, path: str, token: str, body: dict | None = None, opener=urllib.request.urlopen):
    """GitHub REST — 허용 경로 2종만. 반환 (상태, json|None). 본문·토큰은 어디에도 찍지 않는다."""
    if not (path.startswith(f"/repos/{REPO}/actions/workflows/") and (path.endswith("/dispatches") or "/runs?" in path)):
        raise ValueError("허용 안 된 경로")
    r = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                               headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                        "Content-Type": "application/json"})
    try:
        with opener(r, timeout=20) as f:
            raw = f.read()
            return f.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, None


def gas_already(s: dict, now_kst: datetime, token: str, opener=urllib.request.urlopen) -> bool:
    since = (now_kst.replace(hour=s["min"] // 60, minute=s["min"] % 60, second=0, microsecond=0)
             - timedelta(minutes=g.SINCE_PAD_MIN)).astimezone(timezone.utc)
    st, j = _req("GET", f"/repos/{REPO}/actions/workflows/{s['wf']}/runs?event=workflow_dispatch"
                        f"&created=%3E%3D{since.strftime('%Y-%m-%dT%H:%M:%SZ')}&per_page=50", token, opener=opener)
    if st != 200 or not isinstance(j, dict):
        return False   # 확인 실패 → 보낸다 (누락이 중복보다 나쁘다; 중복은 slot_guard 가 거른다)
    return bool(g.primary_ran(j.get("workflow_runs") or [], g.gas_key(s), since))


def run(now_kst: datetime, dry: bool = False, token: str | None = None, opener=urllib.request.urlopen,
        data: Path = DATA, gas: dict | None = None, out=print) -> dict:
    gas = g.parse_gas() if gas is None else gas
    st_p = data / "dispatcher.json"
    try:
        st = json.loads(st_p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        st = {}
    day = now_kst.date().isoformat()
    done = {k for k in st.get("done", []) if k.startswith(day)}
    todo = due(gas, now_kst, done)
    err = None
    for s in todo:
        sid = slot_id(s, day)
        if dry:
            out(f"[dry-run] 보낼 슬롯 {sid}"); continue
        try:
            token = token or load_token()
            if gas_already(s, now_kst, token, opener):
                out(f"{sid} → GAS 가 이미 보냄, 건너뜀"); done.add(sid); continue
            code, _ = _req("POST", f"/repos/{REPO}/actions/workflows/{s['wf']}/dispatches", token,
                           {"ref": "main", "inputs": s["inputs"]}, opener)
            out(f"{sid} → {code}")
            if code == 204:
                done.add(sid); st["last_dispatch"] = now_kst.isoformat(timespec="seconds")
            else:
                err = f"{sid} HTTP {code}"
        except Exception as e:  # noqa: BLE001 — 예외 문구에 토큰이 들어갈 일은 없지만 종류만 남긴다
            err = f"{sid} {type(e).__name__}"
            out(f"{sid} → 실패 {type(e).__name__}")
    if not dry:
        st.update({"last_run": now_kst.isoformat(timespec="seconds"), "done": sorted(done), "last_error": err,
                   "version": "2026-10-21"})
        data.mkdir(parents=True, exist_ok=True)
        st_p.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    if not todo:
        out(f"dispatcher {now_kst:%H:%M} — 보낼 슬롯 없음")
    return st


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now", help="YYYY-MM-DDTHH:MM KST (점검용)")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now).replace(tzinfo=KST) if a.now else datetime.now(KST)
    run(now, dry=a.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
