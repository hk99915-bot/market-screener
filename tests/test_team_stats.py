"""scripts/team_stats.py — 커밋 메시지→데스크 매핑, 보드·요청·감사 집계, stale 판정 (합성 git 로그 없이 함수 단위)."""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import team_stats as ts  # noqa: E402

TASKS = {"mu-revenue-tag": "데이터", "sim-fresh": "개발"}


def test_commit_desk_rules():
    f = lambda m: ts.commit_desk(m, TASKS)
    assert f("dev 라운드1: [운영] 결재 #9 '⛔만 소리'") == "개발"
    assert f("frm 라운드1: 결재 #3 배선") == "리스크"
    assert f("audit 라운드1: slop 감사 데스크 신설") == "감사"
    assert f("lock: apps-script/tab_study.html (교육, aptitude-past)") == "교육"
    assert f("unlock: Index·tab_detail·committee.py (개발)") == "개발"
    assert f("lock: tab_my.html (PB, 분모 (b))") == "PB"                  # 작업명 안 괄호에 안 끌려감
    assert f("board: secret-missing-warning·pbview (개발, P1, 10/20)") == "개발"
    assert f("board: SEC YTD 누적치 결함 의심(P0, 데이터)") == "데이터"
    assert f("board: mu-revenue-tag 상태 대기") == "데이터"                 # 보드 id → owner
    assert f("pb: 보유 텍스트 '예적금' 줄") == "PB"
    assert f("감사: 금액 누출 제거") == "감사"
    assert f("kb(behavior): 복기 4호") == "행동"


def test_commit_desk_unmapped_and_bots():
    assert ts.commit_desk("live: 2026-10-16T20:51", TASKS) is None
    assert ts.commit_desk("LIFE 탭: 목표 표기", TASKS) is None             # 화면 이름은 데스크로 안 셈
    assert ts.commit_desk("valuation: PER 세 분모", TASKS) is None
    assert ts.commit_desk("board: unknown-id 상태", TASKS) is None
    by, un, bots = ts.commit_counts([("screener-bot", "live: x"), ("Claude", "dev 라운드1: y"),
                                     ("Claude", "web: z")], TASKS)
    assert by == {"개발": 1} and un == 1 and bots == 1


def test_norm_owner():
    assert ts.norm_owner("팀장(PB)") == "PB"
    assert ts.norm_owner("개발 누나") == "개발"
    assert ts.norm_owner("frm") == "리스크" and ts.norm_owner("FRM") == "리스크"
    assert ts.norm_owner("peer") == "피어리뷰"


def test_board_counts_and_requests():
    b = {"tasks": [{"owner": "개발", "status": "진행"}, {"owner": "개발", "status": "검수"},
                   {"owner": "dev", "status": "검수"}, {"owner": "PB", "status": "완료"}]}
    c = ts.board_counts(b)
    assert c["개발"]["진행"] == 1 and c["개발"]["검수"] == 2 and c["PB"]["완료"] == 1
    led = {"requests": [{"to": "data", "status": "open"}, {"to": "data", "status": "closed"},
                        {"to": "데이터", "status": "open"}]}
    assert ts.open_requests(led) == {"데이터": 2}


def test_rounds_and_audit(tmp_path):
    (tmp_path / "rounds" / "2026-10-17").mkdir(parents=True)
    (tmp_path / "rounds" / "2026-10-17" / "dev.md").write_text("x", encoding="utf-8")
    (tmp_path / "rounds" / "2026-10-20").mkdir()
    (tmp_path / "rounds" / "2026-10-20" / "dev.md").write_text("x", encoding="utf-8")
    rc = ts.round_counts(tmp_path / "rounds")
    assert rc["개발"] == {"n": 2, "last": "2026-10-20"}
    ad = tmp_path / "audit"; ad.mkdir()
    (ad / "2026-10-01.json").write_text(json.dumps({"by_desk": {"dev": {"중": 9}}}), encoding="utf-8")   # 창 밖
    (ad / "2026-10-17.json").write_text(json.dumps({"by_desk": {"dev": {"치명": 1, "중": 2, "경": 3}}}), encoding="utf-8")
    a, used = ts.audit_counts(ad, date(2026, 10, 14))
    assert a["개발"] == {"치명": 1, "중": 2, "경": 3} and used == ["2026-10-17"]


def test_build_auto_shape(tmp_path):
    auto = ts.build_auto([("Claude", "dev 라운드1: y"), ("screener-bot", "live")],
                         {"tasks": [{"id": "a", "owner": "개발", "status": "대기"}]},
                         {"requests": []}, tmp_path / "none", tmp_path / "none", date(2026, 10, 17))
    d = auto["desks"]["개발"]
    assert d["commits_7d"] == 1 and d["board"]["대기"] == 1 and d["req_open"] == 0
    assert auto["since"] == "2026-10-11" and auto["commits_bot"] == 1


def test_is_stale():
    t = date(2026, 10, 17)
    assert ts.is_stale("2026-10-17T00:07+09:00", t) == 0
    assert ts.is_stale("2026-10-16", t) == 1
    assert ts.is_stale(None, t) == 999 and ts.is_stale("bad", t) == 999


def test_check_exit_code(tmp_path):
    p = tmp_path / "team.json"
    p.write_text(json.dumps({"updated": "2026-01-01", "runs": []}), encoding="utf-8")
    assert ts.main(["--check", "--team", str(p)]) == 1
    p.write_text(json.dumps({"updated": ts.now_kst().strftime("%Y-%m-%dT%H:%M+09:00"), "runs": []}), encoding="utf-8")
    assert ts.main(["--check", "--team", str(p)]) == 0
