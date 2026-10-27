"""오늘의 인적성 생성 규칙 v1 검사 (scripts/apt_daily_check.py, req-edu-11644241 ①)."""
import json
from collections import Counter
from datetime import date, timedelta

import pytest

from scripts import apt_daily_check as A


def _bdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_plan_balanced_every_5_weekdays_and_deterministic():
    days = _bdays(A.RULE_FROM, 10)
    for blk in (days[:5], days[5:]):
        c = Counter(p for d in blk for p in A.plan(d))
        assert [c[i] for i in range(5)] == [3, 3, 3, 3, 3]
    assert A.plan(days[3]) == A.plan(days[3])
    # 주말은 다음 평일 계획과 같은 블록 위치를 쓰지 않는다(평일 수 기준)
    assert len(A.plan(days[0])) == 3


def _item(choices, a, traps):
    return {"type": "자료해석", "q": "q", "choices": choices, "a": a, "exp_ko": "e", "time_sec": 60, "traps": traps}


def test_good_item_passes():
    it = _item(["5,512.0", "5,526.1", "5,546.4", "5,552.4", "5,924.9"], 4, [{"name": "×(1−r)", "value": "5,546.4"}])
    assert A.check_item(it, "x", 4) == []


@pytest.mark.parametrize("mut,frag", [
    (lambda it: it.update(choices=["5,526.1", "5,512.0", "5,546.4", "5,552.4", "5,924.9"]), "오름차순"),
    (lambda it: it.update(traps=[{"name": "×(1−r)", "value": "5,924.9"}]), "정답 보기와 같다"),
    (lambda it: it.update(traps=[{"name": "분모", "value": "9,999"}]), "보기에 없다"),
    (lambda it: it.pop("traps"), "traps 없음"),
    (lambda it: it.update(a=2), "계획"),
])
def test_bad_items_fail(mut, frag):
    it = _item(["5,512.0", "5,526.1", "5,546.4", "5,552.4", "5,924.9"], 4, [{"name": "×(1−r)", "value": "5,546.4"}])
    mut(it)
    errs = A.check_item(it, "x", 4)
    assert any(frag in e for e in errs), errs


def test_sentence_choices_skip_numeric_order():
    it = _item(["항로가 이미 열렸다.", "합의 완료", "합의 불가능", "결론 내릴 수 없다", "운송비 10% 하락"], 3, [{"name": "단정", "value": "합의 완료"}])
    assert A.check_item(it, "x", 3) == []


def test_files_before_rule_are_baseline_only(tmp_path):
    d = date(2026, 10, 21)
    (tmp_path / f"{d}.json").write_text(json.dumps({"aptitude": [_item(["1%", "2%", "3%", "4%", "5%"], 2, None)] * 3}), encoding="utf-8")
    assert A.main(["--dir", str(tmp_path)]) == 0


def test_rule_files_checked_and_position_skew_fails(tmp_path):
    days = _bdays(A.RULE_FROM, 5)
    for d in days:
        items = []
        for want in A.plan(d):
            ch = ["1.0%", "2.0%", "3.0%", "4.0%", "5.0%"]
            trap = ch[(want + 1) % 5]
            items.append(_item(ch, want, [{"name": "분모 바꿔치기", "value": trap}]))
        (tmp_path / f"{d}.json").write_text(json.dumps({"aptitude": items}, ensure_ascii=False), encoding="utf-8")
    assert A.main(["--dir", str(tmp_path)]) == 0
    # 한 파일을 전부 ③ 정답으로 바꾸면 계획 위반으로 실패
    bad = json.loads((tmp_path / f"{days[0]}.json").read_text(encoding="utf-8"))
    for it in bad["aptitude"]:
        it["a"] = 2
        it["traps"] = [{"name": "t", "value": "1.0%"}]
    (tmp_path / f"{days[0]}.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    assert A.main(["--dir", str(tmp_path)]) == 1
