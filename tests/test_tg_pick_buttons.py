"""tg-pick-buttons: 텔레그램 대결 메시지 인라인 버튼 → GAS 웹훅(apps-script/TelegramHook.gs) → pick 이슈.
파이썬 쪽(callback_data 생성·파싱·reply_markup)과 GAS 순수 함수(node 로 실행)가 같은 입력에 같은 이슈 제목·본문을 내는지 대조."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from screener import duel, report

GS = Path(__file__).resolve().parents[1] / "apps-script" / "TelegramHook.gs"
D = "2026-10-21"


# ── 파이썬: callback_data ─────────────────────────────────────────────
def test_callback_roundtrip_kr_us_cash():
    assert duel.parse_pick_cb(duel.pick_cb(D, "KR", "069500")) == {"title": f"pick {D}", "body": "069500 1000000 시가"}
    assert duel.parse_pick_cb(duel.pick_cb(D, "KR", "005930", "c")) == {"title": f"pick {D}", "body": "005930 1000000 종가"}
    assert duel.parse_pick_cb(duel.pick_cb(D, "US", "SPY")) == {"title": f"pick-us {D}", "body": "SPY 1000000"}
    assert duel.parse_pick_cb(duel.pick_cb(D, "US", "QQQ", "5")) == {"title": f"pick-us {D}", "body": "QQQ 1000000 5일"}
    assert duel.parse_pick_cb(duel.pick_cb(D, "KR", "cash")) == {"title": f"pick {D}", "body": "현금"}


@pytest.mark.parametrize("bad", ["", "x", "p|2026-10-21|K|069500", "p|20261021|K|069500|o", "p|2026-10-21|X|069500|o",
                                 "p|2026-10-21|K|069500|s", "p|2026-10-21|K|12|o", "p|2026-10-21|U|TOOLONGX|s", "h|K"])
def test_callback_rejects_bad(bad):
    assert duel.parse_pick_cb(bad) is None


def test_callback_64_byte_limit():
    longest = duel.pick_cb("2026-12-31", "US", "BRK.B-", "5")
    assert len(longest.encode("utf-8")) <= duel.CB_MAX
    with pytest.raises(ValueError):
        duel.pick_cb("2026-10-21", "KR", "X" * 60)
    with pytest.raises(ValueError):
        duel.pick_cb(D, "KR", "069500", "s")   # 미장 청산 코드를 국장에


def test_issue_body_is_what_apply_issue_parses():
    """버튼 본문이 기존 apply_issue 규칙의 첫 줄 형식(종목코드 금액 [시가|종가|5일])과 맞는지 — 같은 정규식으로."""
    import re
    for c, _ in duel.KR_BUTTONS:
        first = duel.parse_pick_cb(duel.pick_cb(D, "KR", c))["body"].split()
        assert re.fullmatch(r"[0-9A-Za-z]{6}|[A-Za-z.]{1,6}", first[0]) and first[1] == str(duel.NOTIONAL)
    for c, _ in duel.US_BUTTONS:
        first = duel.parse_pick_cb(duel.pick_cb(D, "US", c))["body"].split()
        assert re.fullmatch(r"[A-Za-z][A-Za-z.\-]{0,5}", first[0])


# ── 파이썬: 텍스트 ───────────────────────────────────────────────────
TEXTS = [("pick 005930 시가", {"title": "pick K", "body": "005930 시가"}),
         ("pick 005930 1,000,000 종가", {"title": "pick K", "body": "005930 1000000 종가"}),
         ("pick 현금", {"title": "pick K", "body": "현금"}),
         ("/pick cash", {"title": "pick K", "body": "현금"}),
         ("PICK-US qqq 5일", {"title": "pick-us U", "body": "QQQ 5일"}),
         ("pick-us 현금", {"title": "pick-us U", "body": "현금"}),
         ("pick 12", {"error": True}), ("pick", {"error": True}),
         ("안녕", None), ("picks 005930", None), ("pick🔥 005930", None)]


@pytest.mark.parametrize("text,want", TEXTS)
def test_parse_text(text, want):
    got = duel.parse_pick_text(text, "K", "U")
    if want and want.get("error"):
        assert "error" in got
    else:
        assert got == want


# ── reply_markup 구조 · send_telegram 전달 ───────────────────────────
def test_keyboard_structure():
    for mk, btns in (("KR", duel.KR_BUTTONS), ("US", duel.US_BUTTONS)):
        kb = duel.pick_keyboard(D, mk)
        rows = kb["inline_keyboard"]
        assert [b["text"] for b in rows[0]] == [n for _, n in btns]
        assert [b["text"] for b in rows[1]] == ["현금", "✍️ 직접 입력 안내"]
        for b in (b for r in rows for b in r):
            assert set(b) == {"text", "callback_data"} and len(b["callback_data"].encode("utf-8")) <= 64
        assert rows[1][1]["callback_data"] == "h|" + mk[0]
        json.dumps(kb)   # 직렬화 가능


class _Resp:
    status_code = 200
    text = "ok"


def test_send_telegram_attaches_markup_to_last_chunk(monkeypatch):
    calls = []
    monkeypatch.setattr(report.CFG, "telegram_token", "123456789:" + "A" * 35)
    monkeypatch.setattr(report.CFG, "telegram_chat", "-100123")
    monkeypatch.setattr(report.requests, "post", lambda url, data, timeout: calls.append(data) or _Resp())
    kb = duel.pick_keyboard(D, "KR")
    report.send_telegram("\n".join(["줄" * 100] * 80), reply_markup=kb)   # 3800자 넘게 → 여러 조각
    assert len(calls) >= 2
    assert all("reply_markup" not in c for c in calls[:-1])
    assert json.loads(calls[-1]["reply_markup"]) == kb
    calls.clear()
    report.send_telegram("짧음")
    assert "reply_markup" not in calls[0]


def test_duel_messages_send_keyboard():
    """run·run_us·record_pb 의 전송 호출 3곳이 버튼을 붙이는지 (소스 확인 — 네트워크 없는 테스트)."""
    src = Path(duel.__file__).read_text(encoding="utf-8")
    assert src.count("reply_markup=pick_keyboard(") == 3


# ── GAS 순수 함수 (node) — 파이썬과 같은 결과 ─────────────────────────
NODE = shutil.which("node")
_JS = """
const fs = require('fs');
const module = { exports: {} };
new Function('module', fs.readFileSync(process.argv[1], 'utf8'))(module);
const m = module.exports, inp = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = {
  cb: inp.cb.map(x => m.tgParseCallback_(x)),
  tx: inp.tx.map(x => m.tgParseText_(x, 'K', 'U')),
  plans: inp.plans.map(u => m.tgPlan_(u, '42', 'K', 'U')),
  sec: [m.tgSecretOk_({ parameter: { s: 'abc' } }, 'abc'), m.tgSecretOk_({ parameter: { s: 'x' } }, 'abc'),
        m.tgSecretOk_({ parameter: {} }, 'abc'), m.tgSecretOk_({ parameter: { s: '' } }, ''),
        m.tgSecretOk_({ headers: { 'X-Telegram-Bot-Api-Secret-Token': 'abc' }, parameter: {} }, 'abc')],
};
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_gas_matches_python():
    cbs = [duel.pick_cb(D, mk, c) for mk, bs in (("KR", duel.KR_BUTTONS), ("US", duel.US_BUTTONS)) for c, _ in bs]
    cbs += [duel.pick_cb(D, "KR", "cash"), duel.pick_cb(D, "US", "cash"), duel.pick_cb(D, "KR", "005930", "5"),
            duel.pick_cb(D, "US", "soxl", "5"), "p|2026-10-21|K|12|o", "p|bad", "h|K", ""]
    txs = [t for t, _ in TEXTS]
    cq = lambda uid, data: {"update_id": 1, "callback_query": {"id": "q", "from": {"id": uid}, "data": data, "message": {"chat": {"id": 42}}}}
    plans = [cq(42, cbs[0]), cq(7, cbs[0]), cq(42, "h|U"), cq(42, "zzz"),
             {"update_id": 2, "message": {"from": {"id": 42}, "chat": {"id": 42}, "text": "pick 005930 시가"}},
             {"update_id": 3, "message": {"from": {"id": 7}, "chat": {"id": 7}, "text": "pick 005930 시가"}},
             {"update_id": 4, "message": {"from": {"id": 42}, "chat": {"id": 42}, "text": "pick 12"}},
             {"update_id": 5, "message": {"from": {"id": 42}, "chat": {"id": 42}, "text": "고마워"}},
             {"update_id": 6, "edited_message": {}}]
    r = subprocess.run([NODE, "-e", _JS, str(GS)], input=json.dumps({"cb": cbs, "tx": txs, "plans": plans}),
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["cb"] == [duel.parse_pick_cb(x) for x in cbs]
    for got, t in zip(out["tx"], txs):
        py = duel.parse_pick_text(t, "K", "U")
        assert (got is None and py is None) or ("error" in got and "error" in py) or got == py, t
    p = out["plans"]
    assert p[0]["kind"] == "issue" and p[0]["issue"] == duel.parse_pick_cb(cbs[0]) and p[0]["key"] == "tgp:" + cbs[0]
    assert p[1] == {"kind": "ignore", "why": "not-owner"}          # 주인 아닌 사람 버튼
    assert p[2]["kind"] == "help" and "pick-us" in p[2]["text"]
    assert p[3]["kind"] == "bad"
    assert p[4]["kind"] == "issue" and p[4]["issue"] == {"title": "pick K", "body": "005930 시가"}
    assert p[5]["kind"] == "ignore" and p[6]["kind"] == "reply" and p[7]["why"] == "not-pick" and p[8]["kind"] == "ignore"
    assert out["sec"] == [True, False, False, False, True]


# ── 끝까지: 버튼이 연 이슈(GAS 가 본문 뒤에 '(텔레그램 버튼)' 을 붙임)를 기존 apply_issue 가 그대로 기록 ──
@pytest.mark.parametrize("mk,code,want", [("KR", "069500", {"ticker": "069500", "exit": "next_open"}),
                                          ("KR", "cash", {"cash": True}),
                                          ("US", "SPY", {"ticker": "SPY", "exit": "same_close"})])
def test_button_issue_records_via_apply_issue(tmp_path, monkeypatch, mk, code, want):
    from screener import decisions
    monkeypatch.setattr(decisions, "OUT", tmp_path / "decisions.json")
    d = "2026-10-16"
    iss = duel.parse_pick_cb(duel.pick_cb(d, mk, code))
    at = f"{d}T05:00:00Z" if mk == "KR" else f"{d}T12:00:00Z"   # 14:00 KST · 08:00 ET (둘 다 마감 전)
    msg = duel.apply_issue(iss["title"], iss["body"] + "\n\n(텔레그램 버튼)", at)
    assert msg.startswith("기록 완료"), msg
    data = json.loads((tmp_path / "decisions.json").read_text(encoding="utf-8"))
    me = next(x for x in data["items"] if x["id"] == f"{d}-entry" + ("-us" if mk == "US" else ""))["picks"]["나"]
    assert all(me.get(k) == v for k, v in want.items())
