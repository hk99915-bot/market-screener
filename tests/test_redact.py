"""공개 산출물 개인정보 가림 (10/21 감사 D1 — 애널리스트 실명·이메일이 reports/logs/pdf_boxes.json 에 저장됨).
가짜 값만 쓴다. 허용 목록 밖 도메인 예시는 소스에 이메일 모양으로 남지 않게 실행 중에 조립한다(pre-push 검사 대상)."""
import importlib.util
import json
from pathlib import Path

from screener import research
from screener.redact import MASK, mask_emails, public_emails

ROOT = Path(__file__).resolve().parent.parent
FAKE = "analyst@example.com"
CORP = "analyst" + "@" + "fakecorp.co.kr"     # 허용 목록 밖 (회사 도메인 모양)

spec = importlib.util.spec_from_file_location("prepush_check_r", ROOT / "scripts" / "prepush_check.py")
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)


def test_mask_emails_masks_everything_including_example():
    s = f"연구원 홍길동 {FAKE} / {CORP} 02-000-0000"
    out = mask_emails(s)
    assert FAKE not in out and CORP not in out and out.count(MASK) == 2


def test_public_emails_allowlist():
    ok = ["noreply@anthropic.com", "12345+bot@users.noreply.github.com", FAKE, "x@sub.example.org", "y@host.test"]
    assert public_emails(" ".join(ok)) == []
    assert public_emails(f"연락처 {CORP}") == [CORP]


def test_debug_boxes_drops_author_box_and_masks_kept():
    boxes = [
        {"x0": 400, "y1": 700, "w": 120, "keep": False, "t": f"Analyst 홍길동\n{FAKE}"},
        {"x0": 40, "y1": 600, "w": 300, "keep": True, "t": f"본문 문장입니다. 문의 {FAKE}"},
    ]
    out = research._debug_boxes(boxes)
    dumped = json.dumps(out, ensure_ascii=False)
    assert FAKE not in dumped and "홍길동" not in dumped
    assert out[0]["t"].endswith("자 생략]") and out[0]["keep"] is False
    assert out[1]["t"].startswith("본문 문장입니다") and MASK in out[1]["t"]
    assert boxes[0]["t"].startswith("Analyst")      # 원본은 건드리지 않음


def test_summary_masks_email():
    txt = (f"반도체 업황 회복으로 올해 영업이익이 크게 늘어날 것으로 전망된다. 자세한 문의는 담당 연구원 {FAKE} 로 연락 바란다. "
           "메모리 가격 상승이 하반기까지 이어질 것으로 판단함.")
    assert FAKE not in research.summarize_text(txt)


def test_prepush_email_hits_counts_only():
    added = {"reports/logs/x.json": [f'"t": "{CORP}"', f'"ok": "{FAKE}"'], "README.md": ["no email here"]}
    hits = pc.email_hits(added)
    assert hits == {"reports/logs/x.json": 1}


def test_prepush_email_check_blocks_without_printing_value(monkeypatch, capsys):
    monkeypatch.setattr(pc, "added_lines", lambda b, h="HEAD": {"docs/a.md": [CORP]})
    assert pc.email_check(None) is False
    out = capsys.readouterr().out
    assert CORP not in out and "docs/a.md: 1건" in out


def test_prepush_main_fails_on_email(monkeypatch):
    monkeypatch.setattr(pc, "run", lambda name, cmd: True)
    monkeypatch.setattr(pc, "changed_files", lambda b, h="HEAD": [])
    monkeypatch.setattr(pc, "added_lines", lambda b, h="HEAD": {"reports/logs/p.json": [CORP]})
    assert pc.main([]) == 1
    monkeypatch.setattr(pc, "added_lines", lambda b, h="HEAD": {})
    assert pc.main([]) == 0


def test_pdf_boxes_not_tracked():
    assert "reports/logs/pdf_boxes.json" in (ROOT / ".gitignore").read_text(encoding="utf-8")
