"""리서치 종합(screener/research_synthesis.build) — 합성 데이터. 백필 제외·리비전·몰림·괴리·톤 계산을 고정한다."""
from datetime import date, timedelta

import polars as pl

from screener import research_synthesis as rs

D = date(2026, 10, 20)   # 화요일


def _row(d, code, name, broker, tp, op="매수", ca="2026-10-20 19:22", title="AI 수요 회복", summary=None):
    return {"key": f"{d}|{code}|{broker}", "date": d, "source": "한경", "code": code, "name": name, "title": title,
            "broker": broker, "opinion": op, "target": tp, "link": f"https://x/{code}/{broker}/{d}", "collected_at": ca,
            "summary": summary, "analyst": None}


def _store():
    rows = []
    old = D - timedelta(days=40)
    # A: 4개 증권사 하향(직전 40일 전 리포트 대비) — 위원회 롱 후보 → 괴리
    for b in "가나다라":
        rows.append(_row(old, "000001", "가상전자", b + "증권", 100000.0, ca="backfill 2026-10-16 18:28"))
        rows.append(_row(D, "000001", "가상전자", b + "증권", 80000.0))
    # B: 상향 1건, 백필 행이 asof 에 있어도 '신규' 아님
    rows.append(_row(old, "000002", "가상중공업", "가증권", 50000.0, ca="backfill 2026-10-16 18:28"))
    rows.append(_row(D, "000002", "가상중공업", "가증권", 60000.0, ca="backfill 2026-10-21 01:00"))
    return pl.DataFrame(rows, schema=rs.pl.DataFrame(rows).schema)


def _views():
    rows = []
    for i, (k, t) in enumerate([("전략", "반등 기대 회복 개선"), ("매크로", "금리 우려 둔화"), ("채권", "금리 하락 전망. 다음 문장"),
                                ("섹터", "업황 점검")]):
        rows.append({"key": str(i), "date": D, "source": "네이버", "kind": k, "kind_reason": "", "sector": None, "title": t,
                     "broker": "가증권", "analyst": None, "link": f"https://v/{i}", "summary": t + " 요약입니다.", "collected_at": "2026-10-21 01:12"})
    return pl.DataFrame(rows)


META = {"000001": {"theme": "전력기기·전선"}, "000002": {"theme": "조선"}}
CMT = {"ideas": {"long": [{"s": "000001", "n": "가상전자"}], "avoid": [{"s": "000002", "n": "가상중공업"}]},
       "sectors": [{"chain": "전력기기·전선", "stance": "비중 확대"}], "themes": [{"theme": "조선", "r5": 0.05, "r20": 0.1}]}


def test_build_core():
    o = rs.build(_store(), _views(), META, CMT, {"000001": {"tp_upside": 0.3}})
    assert o["label"].startswith("증권가 집계")
    assert o["asof"] == "2026-10-20"
    # 신규 = asof 발간 & 백필 아님 → A 4건만 (B 의 백필 행 제외)
    assert o["inputs"]["new_on_asof"] == 4 and o["inputs"]["backfill_n"] == 6
    r5 = o["revisions"]["d5"]
    assert (r5["up"], r5["down"], r5["n"]) == (1, 4, 5)
    assert r5["top_down"][0]["code"] == "000001" and r5["top_down"][0]["med_tp_chg"] == -0.2
    assert r5["top_down"][0]["reports"][0]["link"].startswith("https://x/000001/")
    # 컨센서스 중앙 변화: A −20%, B +20% → 중앙(정렬 후 len//2) = +20%
    assert o["revisions"]["consensus"]["n_codes"] == 2
    # 섹터 온도: 조선 테마에 위원회 등락 붙음
    sec = {s["theme"]: s for s in o["sectors"]["rows"]}
    assert sec["조선"]["r20"] == 0.1 and sec["전력기기·전선"]["up_ratio"] == 0.0
    # 괴리: A(롱 후보인데 하향 4) · B(회피인데 상향) · 전력기기 비중 확대 vs 상향 0%
    kinds = {(d["type"], d.get("code") or d.get("theme")) for d in o["divergence"]}
    assert ("종목", "000001") in kinds and ("종목", "000002") in kinds and ("섹터", "전력기기·전선") in kinds
    # 몰림: A 5영업일 4건, 직전 0건 → 바닥 0.5 대비 8배
    assert o["crowding"][0]["code"] == "000001" and o["crowding"][0]["x"] == 8.0 and o["crowding"][0]["tp_upside"] == 0.3
    # 톤: 전략·매크로만 (강세 반등·기대·회복·개선 ×2(제목+요약) vs 약세 우려·둔화 ×2)
    t = o["headline"]["tone5"]
    assert t["bull"] == 8 and t["bear"] == 4 and t["index"] == round(4 / 12, 3)
    # 거시·채권 1줄 = 요약 첫 문장
    assert any(m["kind"] == "채권" and m["line"].startswith("금리 하락 전망") for m in o["macro"]["items"])
    assert o["themes"]["rows"] and all(not any(c.isdigit() for c in r["kw"]) for r in o["themes"]["rows"])


def test_bdays_and_tokens():
    assert rs._bdays_back(D, 5) == date(2026, 10, 13)
    assert rs._tokens("영업이익은 AI반도체 수요가 3Q26", set()) == ["AI반도체", "수요"]
    assert rs.tone_of([])["index"] is None
