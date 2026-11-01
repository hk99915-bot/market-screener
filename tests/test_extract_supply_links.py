"""scripts/extract_supply_links.py — DART 본문 공급망 자동 추출 최소 계약(애널 11/1)."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("esl", ROOT / "scripts" / "extract_supply_links.py")
esl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(esl)

PEERS = [
    {"s": "010690", "n": "화신", "g": "자동차", "mc": 3.0e11},
    {"s": "005380", "n": "현대차", "g": "자동차", "mc": 5.0e13},
    {"s": "000270", "n": "기아", "g": "자동차", "mc": 4.0e13},
    {"s": "005490", "n": "POSCO홀딩스", "g": "에너지·소재", "mc": 2.0e13},
    {"s": "055550", "n": "신한지주", "g": "금융", "mc": 3.0e13},
    {"s": "036010", "n": "아비코전자", "g": "전기·전자", "mc": 1.0e11},
]


def _doc(d: Path, code: str, rno: str, kind: str, body: str, name: str = "화신") -> None:
    d.mkdir(exist_ok=True)
    (d / f"{code}_{rno}.txt").write_text(
        f"# {name} ({code}) · {kind} (2026.06) · 접수 {rno[:8]} · rcept_no {rno}\n\nII. 사업의 내용\n\n{body}\n", encoding="utf-8")


def _edges(d):
    return {(e["from"], e["to"]): e for e in d["edges"]}


def test_direction_customer_and_supplier_table(tmp_path):
    biz = tmp_path / "biz"
    _doc(biz, "010690", "20260814000001", "반기보고서",
         "당사의 주요 매출처는 현대자동차(62.5%), 기아 등입니다.\n\n3. 원재료 및 생산설비\n"
         "품목\t주요 매입처\t비율\n강판\t(주)포스코\t40%\n")
    d = esl.build(biz, PEERS, {}, 1300.0)
    E = _edges(d)
    assert E[("010690", "005380")]["type"] == "customer"
    assert "62.5%" in E[("010690", "005380")]["size"]
    assert ("010690", "000270") in E
    sup = E[("005490", "010690")]                    # 매입처는 공급자 → 이 회사
    assert sup["type"] == "supply" and sup["status"] == "1차(자동)"
    assert sup["src"] == "DART 010690 rcept_no 20260814000001"
    n = {x["id"]: x for x in d["nodes"]}
    assert n["010690"]["tier"] == 2 and n["005380"]["tier"] == 1


def test_false_positive_guards(tmp_path):
    biz = tmp_path / "biz"
    _doc(biz, "036010", "20260814000002", "반기보고서",
         "주요 고객사는 애플리케이션 업체 등에 납품하고 있습니다. "
         "경쟁사로는 화신, 기아 등이 있으며 주요 고객으로 점유율을 높이고 있습니다. "
         "아비코전자는 주요 매출처에 공급하고 있습니다. "
         "당사는 고객사 A와 B사에 인덕터를 납품하고 있습니다.", name="아비코전자")
    d = esl.build(biz, PEERS, {}, 1300.0)
    assert d["edges"] == []                          # 애플리케이션≠애플, 경쟁·점유율 문장 제외, 자기 자신 제외
    assert d["stats"]["anon_refs"] >= 1             # 익명 고객은 노드 대신 개수로


def test_halfyear_first_and_equity_holding(tmp_path):
    biz, eq = tmp_path / "biz", tmp_path / "eq"
    _doc(biz, "010690", "20260312000009", "사업보고서", "주요 매출처는 현대차, 기아 등입니다.")
    _doc(biz, "010690", "20260814000003", "반기보고서", "주요 매출처는 현대차 등입니다.")
    eq.mkdir()
    (eq / "055550_x.json").write_text(json.dumps({"rcept_no": "20260814000099", "invest": [
        {"inv_prm": "기아", "trmend_blce_qy_rt": "5.1"}]}, ensure_ascii=False), encoding="utf-8")
    d = esl.build(biz, PEERS, {}, 1300.0, eq)
    E = _edges(d)
    assert E[("010690", "005380")]["src"].endswith("20260814000003")    # 반기 근거 우선
    assert ("010690", "000270") in E                                     # 반기에 없으면 사업보고서 보충
    inv = E[("055550", "000270")]
    assert inv["type"] == "investment" and inv["size"] == "지분율 5.1%" and inv["groups"] == ["sc_finance"]
    assert {x["id"]: x for x in d["nodes"]}["055550"]["tier"] == "holding"
