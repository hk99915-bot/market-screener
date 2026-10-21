"""연구 보드(scripts/research_board.py) — 원장 검증·날짜 추출·미등록 연구 탐지. 동기화(--check)는 CLI 로만 본다(kb:quant 복기 10/17:
공유 산출물 동일성 단언은 남의 연구 파일 하나로 전원 테스트를 깨뜨림) — 여기서는 구조만."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import research_board as rb  # noqa: E402


def test_repo_pipeline_is_valid_and_builds():
    pipe = json.loads(rb.PIPE.read_text(encoding="utf-8"))
    assert rb.validate(pipe) == []
    b = rb.build()
    assert [s["id"] for s in b["stages"]] == list(rb.STAGES)
    assert len(b["items"]) == len(pipe["items"]) >= 1
    assert all(r["text"] and len(r["text"]) <= 140 for r in b["quant_requests"])


def test_committed_board_has_screen_fields():
    b = json.loads(rb.OUT.read_text(encoding="utf-8"))
    for k in ("stages", "verdicts", "challenge", "items", "unregistered", "quant_requests", "asof"):
        assert k in b, k
    for it in b["items"]:
        assert it["stage"] in rb.STAGES and it["verdict"] in rb.VERDICTS and "updated" in it


def test_validate_catches_bad_rows():
    pipe = json.loads(rb.PIPE.read_text(encoding="utf-8"))
    pipe["items"] = [{"id": "x", "stage": "moon", "verdict": "좋음", "name": "n", "owner": "o", "result": "r", "gate": "g", "due": "10/24"},
                     {"id": "x", "stage": "idea", "verdict": "진행", "name": "", "owner": "o", "result": "r", "gate": "g", "auto": ["reports/없는파일.json"]}]
    errs = " | ".join(rb.validate(pipe))
    for w in ("stage moon", "verdict 좋음", "due 형식", "중복", "name 비어", "파일 없음"):
        assert w in errs, w


def test_file_date_rules(tmp_path):
    md = tmp_path / "2026-10-21_x.md"
    md.write_text("> 실계좌 2027-04-15까지 금지\n작성 2026-10-19\n", encoding="utf-8")
    assert rb.file_date(md) == "2026-10-21"            # 파일 이름 날짜 우선
    md2 = tmp_path / "y.md"
    md2.write_text("> 실계좌 2027-04-15까지 금지\n작성 2026-10-19\n", encoding="utf-8")
    assert rb.file_date(md2) == "2026-10-19"           # '까지' 기한 날짜는 건너뜀
    js = tmp_path / "z.json"
    js.write_text(json.dumps({"meta": {"run_at_utc": "2026-10-15T06:12Z"}}), encoding="utf-8")
    assert rb.file_date(js) == "2026-10-15"
    assert rb.file_date(tmp_path / "없음.json") is None


def test_unregistered_studies_listed(tmp_path):
    st = tmp_path / "studies"
    st.mkdir()
    for n in ("fib_levels.json", "newone.md", "replication_fib_levels.json", "trial_log.json"):
        (st / n).write_text("{}" if n.endswith(".json") else "# 2026-10-20\n", encoding="utf-8")
    pipe = json.loads(rb.PIPE.read_text(encoding="utf-8"))
    pipe["items"] = [dict(pipe["items"][0], auto=[], files={}, grades=None)]
    pipe["items"][0]["files"] = {"study": "reports/studies/fib_levels.json"}
    pp = tmp_path / "pipe.json"
    pp.write_text(json.dumps(pipe, ensure_ascii=False), encoding="utf-8")
    b = rb.build(pp, st, tmp_path / "no_reqs.json")
    assert [u["study"] for u in b["unregistered"]] == ["newone"]
