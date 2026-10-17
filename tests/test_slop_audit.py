"""slop_audit 합성 파일 테스트 — 네트워크·git 없이 (e)(f)(b)(c)(g)·STANDARD 4·6 검출."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import slop_audit as sa  # noqa: E402

TODAY = date(2026, 10, 17)


def _mk(tmp: Path, rel: str, text: str) -> Path:
    p = tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_personal_amount_is_critical_and_exit_1(tmp_path):
    _mk(tmp_path, "docs/x.md", "# 메모\n내 계좌 잔고 12,345,678원 보유 중.\n월세 50만원 비유: 옆집 시세가 오르면.\n")
    res = sa.audit(tmp_path, TODAY, git=False)
    crit = [f for f in res["findings"] if f["severity"] == "치명"]
    assert len(crit) == 1 and crit[0]["line"] == 2 and crit[0]["item"] == "(e) 원화 금액"
    assert crit[0]["due"] == "2026-10-17"          # 치명은 당일
    # 비유·시세 문맥은 허용 목록
    assert not [f for f in res["findings"] if f["line"] == 3 and f["item"].startswith("(e)")]
    out = tmp_path / "out"
    rc = sa.main(["--root", str(tmp_path), "--date", "2026-10-17", "--no-git", "--out", str(out)])
    assert rc == 1
    j = json.loads((out / "2026-10-17.json").read_text(encoding="utf-8"))
    assert j["counts"]["치명"] == 1 and (out / "2026-10-17.md").exists()
    assert j["by_desk"]["pb"]["치명"] == 1


def test_allowlisted_amounts_and_account_pattern(tmp_path):
    _mk(tmp_path, "docs/y.md",
        "- 코스피200 선물 거래승수 25만원 [규정]\n- 환율 1,300원 → 1,365원이면 달러 기준 −5%\n- 외국인 현물 +3,662억 순매수\n"
        "- 입금 계좌 110-123-456789 로\n- CIK 0000723125 companyfacts\n")
    res = sa.audit(tmp_path, TODAY, git=False)
    amt = [f for f in res["findings"] if f["item"] == "(e) 원화 금액"]
    assert amt == []
    acct = [f for f in res["findings"] if f["item"] == "(e) 계좌번호 의심"]
    assert len(acct) == 1 and acct[0]["severity"] == "치명" and acct[0]["line"] == 4


def test_broken_path_and_kb_anchor(tmp_path):
    _mk(tmp_path, "docs/desk_kb/frm.md", "# frm\n- #1 [교과서] 손실 비대칭\n- #2 [교과서] 산술\n")
    _mk(tmp_path, "reports/studies/ok.md", "ok")
    _mk(tmp_path, "docs/note.md",
        "출처: reports/studies/ok.md 와 reports/studies/missing.md\n참고 `scripts/nothing.py` kb:frm#2 kb:frm#9 kb:nope#1\n"
        "템플릿 reports/studies/replication_<id>.json 은 건너뜀. https://example.com/docs/none.md 도 건너뜀.\n")
    res = sa.audit(tmp_path, TODAY, git=False)
    broken = {f["evidence"].split(" ← ")[0]: f["severity"] for f in res["findings"] if f["item"] == "(f) 깨진 경로"}
    assert broken == {"reports/studies/missing.md": "중", "scripts/nothing.py": "경"}
    kb = sorted((f["evidence"].split(" — ")[0], f["severity"]) for f in res["findings"] if f["item"] == "(f) kb 앵커")
    assert kb == [("kb:frm#9", "경"), ("kb:nope#1", "중")]


def test_grade_tag_heuristic(tmp_path):
    _mk(tmp_path, "docs/desk_kb/cio.md",
        "# cio\n- 급락 뒤 섹터: rule_audit T5 60일 −3.4%p 차이 — 그래서 방어주 우위.\n"
        "- 급락 뒤 섹터: rule_audit T5 60일 −3.4%p (C, p 0.075) — 방향만.\n"
        "- [교과서] 기대값 예시: rule_audit T3 승률 38% vs 29% 는 손익비로 상쇄.\n")
    res = sa.audit(tmp_path, TODAY, git=False)
    g = [f for f in res["findings"] if f["item"] == "(b) 등급 없는 연구 인용"]
    assert [f["line"] for f in g] == [2] and g[0]["severity"] == "중" and g[0]["desk"] == "cio"


def test_pending_tag_age_and_due(tmp_path):
    old = _mk(tmp_path, "docs/old.md", "기준일 2026-09-01\n- 쿠폰 정의 `[확인 필요]`\n- 다른 것 `[확인 필요: 원문 절, 10/20까지]`\n")
    fresh = _mk(tmp_path, "docs/2026-10-16_new.md", "- 쿠폰 `[확인 필요]`\n")
    res = sa.audit(tmp_path, TODAY, git=False)
    items = {(f["file"], f["item"]): f for f in res["findings"] if f["item"].startswith("(c)")}
    stale = items[("docs/old.md", "(c) 확인 필요 방치")]
    assert stale["severity"] == "중" and "46일" in stale["evidence"]
    assert "1/2건" in items[("docs/old.md", "(c) 확인 필요 기한 없음")]["evidence"]
    assert ("docs/2026-10-16_new.md", "(c) 확인 필요 방치") not in items     # 1일 경과는 통과
    assert ("docs/2026-10-16_new.md", "(c) 확인 필요 기한 없음") in items


def test_commits_without_tests_and_bot_commits_skipped():
    entries = [
        {"hash": "aaa1111", "author": "Claude", "subject": "derivs 라운드1: 레버리지 끌림", "files": ["screener/duel.py", "docs/x.md"]},
        {"hash": "bbb2222", "author": "Claude", "subject": "data 라운드1: 태그 병합", "files": ["screener/sec.py", "tests/test_sec_parse.py"]},
        {"hash": "ccc3333", "author": "screener-bot", "subject": "live: 2026-10-16T20:51", "files": ["screener/live.py"]},
        {"hash": "ddd4444", "author": "Claude", "subject": "docs: KB", "files": ["docs/desk_kb/frm.md"]},
    ]
    out = sa.scan_commits(entries, TODAY)
    assert [f["file"] for f in out] == ["git:aaa1111"] and out[0]["severity"] == "중" and out[0]["desk"] == "derivs"


def test_round_file_voc_request_and_length(tmp_path):
    body = "\n".join(f"- 줄 {i}" for i in range(45))
    _mk(tmp_path, "docs/desk_kb/rounds/2026-10-17/quant.md", "# quant\n" + body + "\n")
    _mk(tmp_path, "docs/desk_kb/rounds/2026-10-17/frm.md", "# frm\n1. 읽기\nVOC: 없음\n요청→cio: 한 줄\n")
    res = sa.audit(tmp_path, TODAY, git=False)
    q = {f["item"] for f in res["findings"] if f["file"].endswith("quant.md")}
    assert {"(6) VOC 줄 없음", "(6) 요청 줄 없음", "(d) 길이 상한"} <= q
    assert not [f for f in res["findings"] if f["file"].endswith("frm.md")]
    assert res["by_desk"]["quant"]["중"] == 2


def test_slop_ok_marker_skips_line(tmp_path):
    _mk(tmp_path, "docs/z.md", "예: 패턴은 '계좌 잔고 1,000,000원' 꼴 <!-- slop:ok -->\n")
    res = sa.audit(tmp_path, TODAY, git=False)
    assert res["findings"] == []
