"""MY 탭 '브라우저 주 + 원장 대조' (docs/my_tab_holdings_plan.md 추천 (a)+(b), 10/17 겸이 승인) 정적·규칙 검사.
- 원장(holdings.txt)을 받아도 확인 없이 덮어쓰지 않는다 (브라우저 값이 비었을 때만 채움)
- 원장 쓰기 없음: PUT 은 회고(journal)뿐, fetch 대상은 pb-private API 뿐
- 메타에는 시각·해시만 · 해시는 공개 저장소에 두지 않음
- 정규화 해시 규칙 = pb:scripts/secrets_gen.py gen_holdings()→digest() (가짜 예문으로 비교)"""
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "apps-script" / "tab_my.html").read_text(encoding="utf-8")
PB_SECRETS = ROOT.parent / "pb-private" / "scripts" / "secrets_gen.py"
# 가짜 보유 예문 (개인 값 아님): 주석·빈 줄·ISA 경계·연속 공백·CRLF·탭 포함
SAMPLE = "# 위성\r\n005930   10  70000\n\n  TIGER 200 IT\t5 30000  \n# 메모\n## ISA\n360750 100 20000\n현금 1000\n"


def _fn(name: str) -> str:
    m = re.search(rf"^function {name}\(.*?(?=^\S)", SRC, re.S | re.M)
    assert m, name
    return m.group(0)


def _py_rule(body: str) -> str:
    """secrets_gen.gen_holdings + digest 와 같은 규칙 (pb-private 가 없는 CI 용 사본)."""
    out = []
    for ln in body.splitlines():
        s = ln.strip()
        if not s or (s.startswith("#") and not re.match(r"^#{1,3}\s*ISA\b", s, re.I)):
            continue
        out.append(re.sub(r"\s+", " ", s))
    norm = "\n".join(l.rstrip() for l in "\n".join(out).strip().splitlines())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def test_sync_no_silent_overwrite():
    sync = _fn("mySync")
    # mySave 는 '브라우저 값이 비어 있을 때' 분기에서만
    assert sync.count("mySave(") == 1
    assert re.search(r"if\(!myNorm\(loc\)\)\{ mySave\(c,'sync'\)", sync)
    assert "MYPEND=c" in sync  # 다르면 보류 → 확인창
    ask = _fn("myAsk")
    for b in ("myaskkeep", "myasktake", "myaskdiff"):
        assert b in ask
    # 바꾸기는 버튼 클릭에서만
    assert re.search(r"\$\('#myasktake'\)\.onclick=\(\)=>\{[^}]*mySave\(c,'sync'\)", ask)


def test_no_ledger_write_and_private_fetch_only():
    assert SRC.count("method:'PUT'") == 1 and "journal: 회고" in SRC   # 쓰기는 회고뿐
    for u in re.findall(r"https://api\.github\.com/repos/[\w.-]+/[\w.-]+", SRC):
        assert u.endswith("hk99915-bot/pb-private"), u
    assert "method:'POST'" not in SRC


def test_meta_has_no_quantities_and_storage_guarded():
    keys = set(re.findall(r"mySetMeta\(\{(\w+):", SRC)) | set(re.findall(r"mySetMeta\(\{\w+:[^,}]+,(\w+):", SRC))
    assert keys <= {"savedAt", "source", "digest", "ledgerDigest", "ledgerAt", "exportedAt"}, keys
    for name in ("myMeta", "mySetMeta", "mySave", "myLoad"):
        assert "try{" in _fn(name), name   # localStorage 접근은 try/catch
    assert "try{ localStorage.setItem(MYMK" in SRC and "try{ return JSON.parse(localStorage.getItem(MYMK)" in SRC


def test_hash_not_in_public_repo():
    reg = list(ROOT.rglob("secret_registry.json")) + list(ROOT.rglob("*holdings*digest*"))
    assert not [p for p in reg if ".git" not in p.parts]


def test_badges_and_export_present():
    for x in ("myledb", "mybakb", "원장: 미확인(토큰 없음)", "마지막 백업 ", "백업 후 수정 있음", "mycopy", "mydl", "myfile", "myimpv",
              "holdings_", "텔레그램·공개 저장소에 붙이지 말 것"):
        assert x in SRC, x
    home = (ROOT / "apps-script" / "tab_home.html").read_text(encoding="utf-8")
    assert "homeLedgerLine" in home and "mySave(" not in home


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_js_digest_matches_secrets_gen_rule():
    isa = re.search(r"const ISA_HEAD=.*?;", SRC).group(0)
    norm = _fn("myNorm")
    dig = re.search(r"async function myDigest\(.*?\n", SRC).group(0)
    js = f"{isa}\n{norm}\n{dig}\nmyDigest({json.dumps(SAMPLE)}).then(d=>console.log(d));"
    got = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30).stdout.strip()
    assert re.fullmatch(r"[0-9a-f]{16}", got), got
    assert got == _py_rule(SAMPLE)
    if PB_SECRETS.exists():   # 비공개 생성기가 있으면 실제 함수와도 맞춰 본다 (CI 엔 없음)
        import importlib.util
        import tempfile
        spec = importlib.util.spec_from_file_location("_sg", PB_SECRETS)
        sg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sg)
        with tempfile.TemporaryDirectory() as d:
            Path(d, "holdings.txt").write_text(SAMPLE, encoding="utf-8", newline="")
            assert got == sg.digest(sg.gen_holdings(d))
