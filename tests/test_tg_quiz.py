"""G3(10/24 겸이 결재, req-dev-4ce51171): 텔레그램 'quiz <qid> <답>' → GAS(apps-script/TelegramHook.gs tgParseQuiz_) → 이슈 'study quiz'
→ study.yml → screener/study_progress.apply_issue. GAS 순수 함수를 node 로 돌려 파이썬 parse_issue 와 같은 줄을 넘기는지 끝까지 대조."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from screener import study_progress as sp

ROOT = Path(__file__).resolve().parents[1]
GS = ROOT / "apps-script" / "TelegramHook.gs"
NODE = shutil.which("node")
SUFFIX = "\n\n(텔레그램 버튼)"   # tgCreateIssue_ 가 본문 뒤에 붙이는 꼬리
_JS = """
const fs = require('fs');
const module = { exports: {} };
new Function('module', fs.readFileSync(process.argv[1], 'utf8'))(module);
const m = module.exports, inp = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify({
  q: inp.tx.map(x => m.tgParseQuiz_(x)),
  plans: inp.tx.map((x, i) => m.tgPlan_({ update_id: i + 1, message: { from: { id: inp.who[i] }, chat: { id: 42 }, text: x } }, '42', 'K', 'U')),
}));
"""


def _bank():
    return json.loads((ROOT / "content" / "study" / "quiz_bank.json").read_text(encoding="utf-8"))


def _node(tx, who=None):
    who = who or [42] * len(tx)
    r = subprocess.run([NODE, "-e", _JS, str(GS)], input=json.dumps({"tx": tx, "who": who}), capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_gas_quiz_parse_matches_python():
    it = _bank()["items"][0]
    right = it["choices"][it["answer"]]
    tx = [f"quiz {it['id']} 2",
          f"QUIZ {it['id']} {right[:4]}\nquiz {it['id']} 1\n고마워",        # 여러 줄 + 인사 줄은 버림
          f"/quiz {it['id']} 3",                                              # 봇 명령 형태
          f"quiz {it['id']} <0~3>\nquiz {it['id']} 0",                        # 번호 안 바꾼 줄은 그대로 넘겨 파이썬이 bad 로
          "quiz", f"quiz {it['id']}", "quizz H2-b1 1", "안녕 quiz H2-b1 1", "pick 005930 시가", "ask 퀀트 언제?"]
    out = _node(tx)
    q = out["q"]
    assert q[0] == {"title": "study quiz", "body": f"quiz {it['id']} 2"}
    assert q[1]["body"] == f"QUIZ {it['id']} {right[:4]}\nquiz {it['id']} 1"
    assert q[2]["body"] == f"quiz {it['id']} 3"
    assert "error" in q[4] and "error" in q[5]                     # 답 없음 → 형식 안내
    assert q[6] is None and q[7] is None and q[8] is None and q[9] is None
    # GAS 가 연 이슈(제목·본문+꼬리)를 study.yml 이 부르는 파이썬이 원문과 똑같이 읽는다
    for t, g in zip(tx[:4], q[:4]):
        assert g["title"] == "study quiz"
        got = sp.parse_issue(g["title"], g["body"] + SUFFIX)
        want = sp.parse_issue("study quiz", "\n".join(l.lstrip("/") for l in t.splitlines()))
        assert got == want and got["quiz_only"] and got["id"] is None, t
    assert sp.parse_issue(q[3]["title"], q[3]["body"])["bad"] == [f"quiz {it['id']} <0~3>"]
    p = out["plans"]
    assert p[0]["kind"] == "issue" and p[0]["issue"] == q[0] and p[0]["key"] == "tgt:study quiz|" + q[0]["body"]
    assert p[4]["kind"] == "reply" and "quiz <문항id> <답>" in p[4]["text"]
    assert p[6] == {"kind": "ignore", "why": "not-pick"}
    assert p[8]["issue"]["title"].startswith("pick ") and p[9]["issue"]["title"] == "ask 퀀트"   # 기존 경로 그대로


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_gas_quiz_ignores_non_owner():
    out = _node(["quiz H2-b1 1"], who=[7])
    assert out["plans"][0] == {"kind": "ignore", "why": "not-owner"}


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_gas_quiz_issue_records_via_apply_issue(tmp_path):
    """끝까지: GAS 본문 → apply_issue 가 퀴즈만 기록(모듈 done 없음)."""
    for rel in ("content/study.json", "content/study/quiz_bank.json", "content/study/srs.json"):
        src = ROOT / rel
        if src.exists():
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, tmp_path / rel)
    (tmp_path / "reports").mkdir()
    it = next(x for x in _bank()["items"] if x["module"] == "R1")
    g = _node([f"quiz {it['id']} {it['choices'][it['answer']]}"])["q"][0]
    msg = sp.apply_issue(g["title"], g["body"] + SUFFIX, "2026-10-24T12:00:00Z", root=tmp_path)
    assert "퀴즈 1문항 기록" in msg
    prog = json.loads((tmp_path / "reports" / "study_progress.json").read_text(encoding="utf-8"))
    assert prog["done"] == [] and prog["quiz"][0]["qid"] == it["id"] and prog["quiz"][0]["ok"] is True


def test_study_workflow_accepts_quiz_title():
    """study.yml 조건 'study ' 시작 — 'study quiz' 가 걸리는지 (조건 변경 불필요 확인)."""
    y = (ROOT / ".github" / "workflows" / "study.yml").read_text(encoding="utf-8")
    assert "startsWith(github.event.issue.title, 'study ')" in y and "study quiz".startswith("study ")
