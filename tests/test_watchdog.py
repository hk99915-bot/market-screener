"""watchdog-b · requests-e (10/21 PM 안 B·E + 겸이 사내 메신저): 감지 5종·요청 2영업일 승격·ask 파서(파이썬=GAS)·단톡 요약 렌더."""
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ask  # noqa: E402
import round_collect as rc  # noqa: E402
import watchdog as wd  # noqa: E402
import team_run  # noqa: E402

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 21, 0, 7, tzinfo=KST)
GS = ROOT / "apps-script" / "TelegramHook.gs"


def _task(tid, **kw):
    t = {"id": tid, "title": tid, "owner": "개발", "priority": "P2", "status": "대기", "started": None, "due": None,
         "repo": "public", "files": [], "depends_on": [], "notes": ""}
    t.update(kw)
    return t


def _w(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


# ── 감지 5종: 각 1건 ────────────────────────────────────────────────
def test_detect_zero_status_views_research_accum(tmp_path):
    _w(tmp_path / "reports" / "deriv_hist_status.json", {"n_errors": 2, "errors": ["x", "y"], "rows": 10})
    _w(tmp_path / "reports" / "fine_status.json", {"overall": "ok", "rows": 5})
    _w(tmp_path / "reports" / "research_views.json", {"status": {"overall": "partial"}})
    _w(tmp_path / "reports" / "research.json", {"items": []})
    f = wd.detect_zero(tmp_path)   # accum.json 없음 → 결측
    got = {(x["id"], x["owner"]) for x in f}
    assert got == {("deriv_hist_status", "파생"), ("research_views", "애널"), ("research", "데이터"), ("accum", "퀀트")}
    assert all(x["kind"] == "zero" for x in f)


def test_detect_fresh_reuses_freshness_and_splits_toss():
    late = {"late": [{"id": "detail_kr", "path": "reports/detail/KR/_index.json", "expected": "2026-10-20", "actual": "2026-10-19"},
                     {"id": "toss_md", "path": "toss-live:live.json", "expected": "2026-10-20", "actual": None}]}
    f = wd.detect_fresh(NOW, check=lambda: late)
    assert [(x["kind"], x["owner"]) for x in f] == [("fresh", "운영"), ("toss", "데이터")]
    assert wd.detect_fresh(NOW, check=lambda: (_ for _ in ()).throw(RuntimeError("x")))[0]["kind"] == "fresh"


def test_detect_board_overdue_and_waiting():
    b = {"tasks": [_task("late", due="2026-10-20", status="검수"), _task("done", due="2026-10-01", status="완료"),
                   _task("old-wait", owner="퀀트"), _task("new-wait"), _task("wd-zero-x", due="2026-10-01")]}
    f = wd.detect_board(b, "2026-10-21", {"old-wait": "2026-10-18", "new-wait": "2026-10-20"})
    assert [(x["kind"], x["task"]) for x in f] == [("overdue", "late"), ("waiting", "old-wait")]


def test_escalate_keeps_priority_opens_and_autocloses_wd():
    b = {"tasks": [_task("late", priority="P3", due="2026-10-01"), _task("wd-zero-gone"), _task("prev", escalated="2026-10-19")]}
    fs = [wd.F("overdue", "개발", "late", "m", task="late"), wd.F("overdue", "개발", "prev", "m", task="prev"),
          wd.F("zero", "데이터", "accum", "accum.json 결측")]
    B, n_new, n_closed = wd.escalate(b, fs, "2026-10-21")
    t = {x["id"]: x for x in B["tasks"]}
    assert t["late"]["priority"] == "P3" and t["late"]["escalated"] == "2026-10-21"
    assert t["prev"]["escalated"] == "2026-10-19"                       # 처음 날짜 유지
    assert t["wd-zero-accum"]["priority"] == "P1" and t["wd-zero-accum"]["owner"] == "데이터"
    assert t["wd-zero-gone"]["status"] == "완료" and n_new == 2 and n_closed == 1
    assert b["tasks"][0].get("escalated") is None                       # 원본 불변
    import importlib.util
    spec = importlib.util.spec_from_file_location("board_mod", ROOT / "scripts" / "board.py")
    bm = importlib.util.module_from_spec(spec); spec.loader.exec_module(bm)
    assert bm.validate(B) == []


# ── E: 날짜 기준 2영업일 승격 (휴장일 반영) ────────────────────────────
def test_request_promotes_after_two_business_days():
    L = {"requests": [{"id": "req-dev-1", "from": "ops", "to": "dev", "text": "t", "opened": "2026-10-08", "status": "open"}]}
    assert rc.biz_days("2026-10-08", "2026-10-12") == 1                 # 10/9 한글날 휴장 · 주말 제외
    assert rc.promotions(L, "2026-10-12", {"tasks": []}) == []
    t = rc.promotions(L, "2026-10-13", {"tasks": []})
    assert len(t) == 1 and t[0]["priority"] == "P1" and t[0]["owner"] == "개발" and t[0]["escalated"] == "2026-10-13"
    assert "pending_bdays" not in L["requests"][0]                       # 장부 원본 불변


# ── ask: 장부 추가·닫기 · 파서 ───────────────────────────────────────
def test_ask_add_close_and_dedupe():
    L, r = ask.add({}, "퀀트", "data", "accum 백필 일정 회신\n\n(텔레그램 버튼)", None, NOW)
    assert (r["from"], r["to"], r["text"], r["status"]) == ("quant", "data", "accum 백필 일정 회신", "open")
    assert r["due"] == "2026-10-23" and r["opened_at"].startswith("2026-10-21T00:07")
    L2, r2 = ask.add(L, "quant", "데이터", "accum 백필 일정 회신", None, NOW)
    assert len(L2["requests"]) == 1 and r2["id"] == r["id"]
    L3, _ = ask.add(L2, "겸이", "매크로", "금리 칩 설명", "2026-10-30", NOW)
    assert any(x["from"] == "겸이" and x["due"] == "2026-10-30" for x in L3["requests"])
    L4, c = ask.close(L3, r["id"], "데이터", NOW)
    assert c["status"] == "done" and c["done"] == "2026-10-21"
    with pytest.raises(ValueError):
        ask.add({}, "퀀트", "없는데스크", "x", None, NOW)


ASKS = [("ask 퀀트 accum 백필 언제?", {"desk": "퀀트", "text": "accum 백필 언제?"}), ("/ASK data 확인 부탁", {"desk": "데이터", "text": "확인 부탁"}),
        ("ask 없는데스크 x", "error"), ("ask 퀀트", "error"), ("ask", "error"), ("asked 퀀트 x", None), ("pick 005930", None)]


@pytest.mark.parametrize("text,want", ASKS)
def test_parse_ask_text(text, want):
    got = ask.parse_ask_text(text)
    assert ("error" in got) if want == "error" else got == want


def test_ask_issue_path(tmp_path):
    led = tmp_path / "_requests.json"
    assert ask.main(["--issue-title", "ask 퀀트", "--issue-body", "accum 백필 언제?\n\n(텔레그램 버튼)", "--ledger", str(led)]) == 0
    r = json.loads(led.read_text(encoding="utf-8"))["requests"][0]
    assert r["from"] == "겸이" and r["to"] == "quant" and r["text"] == "accum 백필 언제?"
    assert ask.main(["--issue-title", "ask 모름", "--ledger", str(led)]) == 2


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_gas_ask_matches_python():
    js = """
const fs = require('fs'); const module = { exports: {} };
new Function('module', fs.readFileSync(process.argv[1], 'utf8'))(module);
const m = module.exports, inp = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify({ desks: m.TG_DESKS, ask: inp.map(x => m.tgParseAsk_(x)),
  plan: m.tgPlan_({ update_id: 9, message: { from: { id: 42 }, chat: { id: 42 }, text: 'ask 퀀트 백필?' } }, '42', 'K', 'U'),
  pick: m.tgPlan_({ update_id: 10, message: { from: { id: 42 }, chat: { id: 42 }, text: 'pick 005930 시가' } }, '42', 'K', 'U') }));
"""
    r = subprocess.run([shutil.which("node"), "-e", js, str(GS)], input=json.dumps([t for t, _ in ASKS]),
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["desks"] == rc.DESKS
    for got, (t, _) in zip(out["ask"], ASKS):
        py = ask.parse_ask_text(t)
        if py is None or "error" in py:
            assert (got is None) == (py is None) and (got is None or "error" in got), t
        else:
            assert got == {"title": "ask " + py["desk"], "body": py["text"]}, t
    assert out["plan"]["kind"] == "issue" and out["plan"]["issue"] == {"title": "ask 퀀트", "body": "백필?"}
    assert out["pick"]["issue"] == {"title": "pick K", "body": "005930 시가"}      # 기존 pick 처리 그대로


# ── 단톡 요약 렌더 · run 끝까지 ─────────────────────────────────────
def test_render_quiet_is_one_line_and_messenger_section():
    base = {"date": "2026-10-21", "by_owner": {}, "counts": {k: 0 for k in wd.KIND_KO}, "messenger": {"new": [], "closed": [], "promoted": []}}
    assert wd.render(base) == "🐶 watchdog 10/21 · 이상 없음"
    L = {"requests": [
        {"id": "a", "from": "겸이", "to": "quant", "text": "백필 언제?", "opened": "2026-10-20", "opened_at": "2026-10-20T09:00+09:00", "due": "2026-10-22", "status": "open"},
        {"id": "b", "from": "ops", "to": "dev", "text": "--add", "opened": "2026-10-10", "status": "done", "done": "2026-10-20"},
        {"id": "c", "from": "data", "to": "frm", "text": "오래됨", "opened": "2026-10-01", "opened_at": "2026-10-01T09:00+09:00", "status": "open"}]}
    m = wd.messenger(L, NOW)
    assert m == {"new": ["겸이 → 퀀트: 백필 언제?(2026-10-22)"], "closed": ["운영 → 개발: --add(—)"], "promoted": []}
    txt = wd.render({**base, "messenger": m})
    assert txt.splitlines()[0] == "🐶 watchdog 10/21 · 이상 없음" and "📮 사내 메신저 (24h)" in txt
    assert "새 · 겸이 → 퀀트: 백필 언제?(2026-10-22)" in txt and "닫힘 · 운영 → 개발" in txt


def test_run_apply_end_to_end(tmp_path, monkeypatch):
    _w(tmp_path / "ops" / "board.json", {"tasks": [_task("late", due="2026-10-01")]})
    _w(tmp_path / "docs" / "desk_kb" / "rounds" / "_requests.json",
       {"requests": [{"id": "req-dev-x", "from": "ops", "to": "dev", "text": "t", "opened": "2026-10-16", "status": "open"}]})
    _w(tmp_path / "reports" / "accum.json", {"status": "ok", "n": 3})
    sent = []
    import screener.report as rep
    monkeypatch.setattr(rep, "send_telegram", lambda text, **k: sent.append(text))
    msgs = []
    res = wd.run(NOW, tmp_path, apply=False, out=msgs.append, fresh_check=lambda: {"late": []}, first_seen={})
    assert not (tmp_path / "reports" / "watchdog.json").exists() and res["counts"]["overdue"] == 1 and res["counts"]["request"] == 1
    res = wd.run(NOW, tmp_path, apply=True, send=True, out=msgs.append, fresh_check=lambda: {"late": []}, first_seen={})
    B = json.loads((tmp_path / "ops" / "board.json").read_text(encoding="utf-8"))
    t = {x["id"]: x for x in B["tasks"]}
    assert t["late"]["escalated"] == "2026-10-21" and t["late"]["priority"] == "P2" and t["req-dev-x"]["priority"] == "P1"
    L = json.loads((tmp_path / "docs" / "desk_kb" / "rounds" / "_requests.json").read_text(encoding="utf-8"))
    assert L["requests"][0]["status"] == "promoted"
    assert len(sent) == 1 and "승격 · 운영 → 개발: t" in sent[0] and set(res["by_owner"]) == {"개발"}
    wd.run(NOW, tmp_path, apply=True, send=True, out=msgs.append, fresh_check=lambda: {"late": []}, first_seen={})
    assert len(sent) == 1                                                  # 하루 1통


def test_team_run_trigger_field(tmp_path, monkeypatch):
    p = tmp_path / "team.json"
    p.write_text(json.dumps({"runs": [{"date": "2026-10-01", "owner": "PM", "task": "old", "tokens": 1}]}), encoding="utf-8")
    monkeypatch.setattr(team_run, "P", p)
    team_run.main(["--owner", "개발", "--task", "x", "--tokens", "1", "--tools", "2", "--sec", "3", "--trigger", "auto", "--date", "2026-10-21"])
    team_run.main(["--owner", "개발", "--task", "y", "--tokens", "1", "--tools", "2", "--sec", "3", "--date", "2026-10-21"])
    runs = json.loads(p.read_text(encoding="utf-8"))["runs"]
    assert "trigger" not in runs[0] and runs[1]["trigger"] == "auto" and runs[2]["trigger"] == "pb"
