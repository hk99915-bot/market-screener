import importlib, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
pc = importlib.import_module("proofcheck")

ORIG = "반도체 비중은 22.3%다. 스트레스는 −15.68%로 한도를 넘었다. \"치유 매도는 대기\"라고 정했다."


def test_read_counts_translationese_and_passive():
    r = pc.read("이 문제에 있어서 검토가 필요하다. 결과는 보여진다. 귀추가 주목된다.")
    assert r["translationese"] >= 1 and r["passive"] >= 1 and r["cliche"] >= 1 and 0 <= r["score"] <= 100


def test_compare_ok_on_light_edit():
    new = "반도체 비중은 22.3%다. 스트레스는 −15.68%로 한도를 넘었다. \"치유 매도는 대기\"라고 정했다."
    assert pc.compare(ORIG, new)["verdict"] == "ok"


def test_compare_blocks_new_number_quote_register():
    assert any("숫자" in b for b in pc.compare(ORIG, ORIG.replace("22.3%", "25.0%"))["block"])
    assert any("인용" in b for b in pc.compare(ORIG, ORIG.replace("\"치유 매도는 대기\"", "치유 매도 보류"))["block"])
    polite = "반도체 비중은 22.3%입니다. 스트레스는 −15.68%로 한도를 넘었습니다. \"치유 매도는 대기\"라고 정했습니다."
    assert any("말투" in b for b in pc.compare(ORIG, polite)["block"])


def test_compare_blocks_rewrite():
    r = pc.compare(ORIG, "완전히 다른 글이다. 내용도 바뀌었다. 아무 관련 없다.")
    assert r["verdict"] == "block"
