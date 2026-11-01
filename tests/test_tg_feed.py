"""scripts/tg_common.py·tg_feed.py — 공개 텔레그램 미리보기 파싱(답장 미리보기 제외)·새 글만·첫 줄 120자·사진 URL·답장/전달·직전 3개·og·연락처 삭제·채널 설정·변경 없으면 파일 그대로.

샘플은 https://t.me/s/akacommodity·hedgehara (2026-11-01 조회) 글 조각을 줄인 것(스타일·이미지 주소 일부 생략).
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import tg_common as tg  # noqa: E402
import tg_feed  # noqa: E402

POST_24844 = '''<div class="tgme_widget_message_wrap js-widget_message_wrap"><div class="tgme_widget_message js-widget_message" data-post="akacommodity/24844" data-view="x">
<a class="tgme_widget_message_reply user-color-default" href="https://t.me/akacommodity/24778">
<div class="tgme_widget_message_text js-message_reply_text" dir="auto"><i class="emoji"><b>🇬🇧</b></i>&lt;LME Week 탐방기, 그럼에도 여전한 낙관론(10/29)&gt; (대신증권 원자재/파생상품)</div>
</a>
<div class="tgme_widget_message_text js-message_text" dir="auto">칩플레이션 진정(공급 증가)이 중요한 이유는 AI 산업화 성장 + 전통 산업 회복에 모두 도움이 될 수 있기 때문입니다. 그 논리는 이번 LME Week 탐방기 자료에 담겨 있습니다.<br/><br/><a href="https://www.zerohedge.com/markets/flash-crash-kioxia-warns-nand-price-surge-ending-sending-sandisk-plunging" target="_blank" rel="noopener">https://www.zerohedge.com/markets/flash-crash-kioxia-warns-nand-price-surge-ending-sending-sandisk-plunging</a></div><a class="tgme_widget_message_link_preview" href="https://zerohedge.com/markets/flash-crash-kioxia-warns-nand-price-surge-ending-sending-sandisk-plunging">
<div class="link_preview_title" dir="auto">Flash Crash: Kioxia Warns NAND Price Surge Ending</div></a>
<div class="tgme_widget_message_footer compact js-message_footer"><a class="tgme_widget_message_date" href="https://t.me/akacommodity/24844"><time datetime="2026-10-31T00:20:51+00:00" class="time">00:20</time></a></div></div></div>'''

POST_24869 = '''<div class="tgme_widget_message js-widget_message" data-post="akacommodity/24869" data-view="x">
<div class="tgme_widget_message_text js-message_text" dir="auto"><a href="https://n.news.naver.com/article/050/0000112680?type=breakingnews&amp;cds=news_edit" target="_blank" rel="noopener">https://n.news.naver.com/article/050/0000112680?type=breakingnews&amp;cds=news_edit</a></div>
<div class="tgme_widget_message_footer compact js-message_footer"><time datetime="2026-11-01T04:32:24+00:00" class="time">04:32</time></div></div>'''

POST_PHOTO_FWD = """<div class="tgme_widget_message js-widget_message" data-post="hedgehara/49071" data-view="x">
<div class="tgme_widget_message_forwarded_from accent_color">Forwarded from&nbsp;<span class="tgme_widget_message_forwarded_from_name">ba nana</span></div>
<a class="tgme_widget_message_photo_wrap 1 2" href="https://t.me/hedgehara/49071" style="width:800px;background-image:url('https://cdn5.telesco.pe/file/AbC_dEf.jpg')"><div class="tgme_widget_message_photo"></div></a>
<div class="tgme_widget_message_text js-message_text" dir="auto">문의 someone@example.com 010-1234-5678 차트 봐라<br/>둘째 줄</div>
<div class="tgme_widget_message_footer compact js-message_footer"><time datetime="2026-11-01T05:00:00+00:00" class="time">05:00</time></div></div>"""

POST_FWD_CH = """<div class="tgme_widget_message js-widget_message" data-post="d_ticker/900" data-view="x">
<div class="tgme_widget_message_forwarded_from accent_color">Forwarded from&nbsp;<a class="tgme_widget_message_forwarded_from_name" href="https://t.me/akacommodity/24869"><span dir="auto">대신증권 원자재</span></a></div>
<div class="tgme_widget_message_text js-message_text" dir="auto">마이크로소프트도 $25B 회사채를 발행</div>
<div class="tgme_widget_message_footer compact js-message_footer"><time datetime="2026-11-01T06:00:00+00:00" class="time">06:00</time></div></div>"""

NOW = datetime(2026, 11, 1, 20, 13, tzinfo=tg.KST)
CFG_S = {"name": "akacommodity", "type": "sellside", "holding_disclosure": False, "out": "tg_commodity.json"}
CFG_I = {"name": "hedgehara", "type": "individual", "holding_disclosure": False, "out": "tg_hedgehara.json"}
FIELDS = {"id", "at", "head", "link", "images", "og", "ctx"}


def test_parse_skips_reply_preview_and_keeps_links():
    p = tg.parse_page(POST_24844)[0]
    assert p["post_id"] == 24844 and p["channel"] == "akacommodity"
    assert p["first_line"].startswith("칩플레이션 진정")            # 답장 미리보기(LME Week)가 아니라 본 글
    assert p["links"][0].startswith("https://www.zerohedge.com/") and len(p["links"]) == 2   # 본문 링크 + 미리보기
    assert p["reply_to"] == {"channel": "akacommodity", "id": 24778} and p["images"] == []


def test_item_fields_head_link_og():
    it = tg_feed.to_item(tg.parse_page(POST_24844)[0], [24840, 24841, 24842, 24843],
                         og_fetch=lambda u: {"title": "Flash Crash", "site": "ZeroHedge"})
    assert set(it) == FIELDS and it["at"] == "2026-10-31T09:20+09:00" and len(it["head"]) <= 120
    assert it["og"] == {"title": "Flash Crash", "site": "ZeroHedge"}
    assert it["ctx"]["prev"] == [24843, 24842, 24841] and it["ctx"]["reply_to"]["id"] == 24778
    it2 = tg_feed.to_item(tg.parse_page(POST_24869)[0], [])
    assert it2["link"] == "https://n.news.naver.com/article/050/0000112680?type=breakingnews&cds=news_edit"
    assert it2["og"] == {"title": "", "site": ""}                       # og 조회 안 하면 빈 값


def test_photo_forward_and_contact_scrub():
    it = tg_feed.to_item(tg.parse_page(POST_PHOTO_FWD)[0], [])
    assert it["images"] == ["https://cdn5.telesco.pe/file/AbC_dEf.jpg"]
    assert it["ctx"]["fwd_from"] == {"channel": ""}                     # 개인 원본 — 이름 저장 안 함
    assert "ba nana" not in json.dumps(it, ensure_ascii=False)
    assert "@" not in it["head"] and "1234" not in it["head"] and "둘째 줄" not in it["head"]
    ch = tg.parse_page(POST_FWD_CH)[0]
    assert ch["fwd_from"] == {"channel": "akacommodity", "id": 24869}


def test_long_body_truncated():
    long = POST_24869.replace('<a href', "가" * 300 + "<br/>둘째 줄<br/><a href")
    it = tg_feed.to_item(tg.parse_page(long)[0], [])
    assert it["head"] == "가" * 120                                   # 첫 줄 120자만, 둘째 줄·본문 없음


def test_merge_new_only_state_label():
    posts = tg.parse_page(POST_24844 + POST_24869)
    doc = tg_feed.merge({}, CFG_S, posts, 200, NOW)
    assert [x["id"] for x in doc["posts"]] == [24869, 24844] and doc["label"] == "셀사이드"
    assert doc["posts"][0]["ctx"]["prev"] == [24844]
    assert tg.last_id(doc["state"], "akacommodity") == 24869
    again = tg_feed.merge(doc, CFG_S, posts[:1], 1, NOW)
    assert [x["id"] for x in again["posts"]] == [24869]                # keep 상한, 최신 우선
    ind = tg_feed.merge({}, CFG_I, tg.parse_page(POST_PHOTO_FWD), 200, NOW)
    assert ind["type"] == "individual" and ind["label"] == "개인 채널·보유 가능성"


def test_config_one_place_and_types():
    chans = tg_feed.load_config()
    names = {c["name"]: c for c in chans}
    assert {"akacommodity", "Samsung_Global_AI_SW", "hedgehara", "The_MariTimes", "d_ticker", "Trillion_labs"} <= set(names)
    assert names["d_ticker"]["holding_disclosure"] is True and names["d_ticker"]["type"] == "individual"
    assert names["Samsung_Global_AI_SW"]["type"] == "sellside"
    assert len({c["out"] for c in chans}) == len(chans)


def test_collect_stops_at_last_id():
    pages = {None: POST_24869, 24869: POST_24844}
    calls = []

    def fake(ch, before):
        calls.append(before)
        return pages.get(before, "")

    assert [p["post_id"] for p in tg.collect("akacommodity", 0, 2, fake)] == [24844, 24869]
    calls.clear()
    assert [p["post_id"] for p in tg.collect("akacommodity", 24868, 2, fake)] == [24869] and calls == [None]


def test_no_new_posts_leaves_file_untouched(tmp_path, monkeypatch):
    out = tmp_path / "tg_commodity.json"
    out.write_text(json.dumps({"state": {"akacommodity": {"last_id": 24869}}, "posts": []}), encoding="utf-8")
    before = out.read_text(encoding="utf-8")
    monkeypatch.setattr(tg, "fetch", lambda ch, before=None: POST_24844 + POST_24869)
    assert tg_feed.run_one(CFG_S, 2, 200, False, tmp_path) == 0
    assert out.read_text(encoding="utf-8") == before                    # 변경 없으면 파일 그대로 → 커밋 없음


def test_why_file_created_once(tmp_path):
    p = tmp_path / "tg_why.json"
    chans = tg_feed.load_config()
    tg_feed.ensure_why(p, chans)
    d = json.loads(p.read_text(encoding="utf-8"))
    assert set(d["format"]) == {"post_id", "why", "thesis_link", "conf"} and d["items"] == []
    sc = d["channel_scores"]
    assert set(sc) == {c["name"] for c in chans}
    assert {"new_info_ratio", "port_link_ratio", "leading", "noise_ratio"} <= set(sc["d_ticker"])
    assert all(v is None for k, v in sc["d_ticker"].items() if k in d["score_format"])   # 값은 데스크가 채움
    p.write_text('{"items": [1]}', encoding="utf-8")
    tg_feed.ensure_why(p, chans)
    assert p.read_text(encoding="utf-8") == '{"items": [1]}'            # 데스크가 쓴 파일은 안 건드림


def test_scrub_keeps_url_digits():
    assert tg_feed.scrub("https://n.news.naver.com/article/050/0000112680?x") == "https://n.news.naver.com/article/050/0000112680?x"
    assert "5678" not in tg_feed.scrub("연락 01012345678") and "example.test" not in tg_feed.scrub("a.b@example.test")


MF = """<div class="tgme_widget_message js-widget_message" data-post="marketfeed/{id}" data-view="x">
<div class="tgme_widget_message_text js-message_text" dir="auto">{text}</div>
<div class="tgme_widget_message_footer compact js-message_footer"><time datetime="{at}" class="time">x</time></div></div>"""


def test_headline_mode_hits_no_why_keep_days():
    cfg = [c for c in tg_feed.load_config() if c["name"] == "marketfeed"][0]
    assert cfg["mode"] == "headline" and cfg["max_pages"] == 10 and cfg["keep_days"] == 7
    page = (MF.format(id=10, text="SAMSUNG ELECTRONICS TO RAISE HBM PRICES", at="2026-11-01T01:00:00+00:00")
            + MF.format(id=11, text="Fed's Waller: no rush to cut", at="2026-11-01T02:00:00+00:00")
            + MF.format(id=12, text="Hyperscaler capex guidance raised again", at="2026-11-01T02:30:00+00:00")
            + MF.format(id=13, text="Football: club fed up with referee? no — Liverpool wins", at="2026-11-01T03:00:00+00:00")
            + MF.format(id=5, text="old headline oil", at="2026-10-20T03:00:00+00:00"))
    doc = tg_feed.merge({}, cfg, tg.parse_page(page), 2000, NOW, og_fetch=lambda u: 1 / 0)   # og 조회 안 함
    by = {x["id"]: x for x in doc["posts"]}
    assert doc["why"] == "hit 글만" and doc["tier"] == 1 and doc["mode"] == "headline"
    assert set(by[10]["hit"]) == {"Samsung", "HBM"} and by[11]["hit"] == ["Fed"]
    assert by[12]["hit"] == ["hyperscaler capex"]
    assert 5 not in by                                                     # 7일 넘은 글은 버림
    assert doc["hit_count"] == sum(1 for x in doc["posts"] if x["hit"])


def test_channel_list_closed_at_nine():
    chans = tg_feed.load_config()
    assert len(chans) == 9
    assert {c["name"] for c in chans if c["tier"] == 1} == {"akacommodity", "Samsung_Global_AI_SW", "marketfeed"}
    assert all(c["tier"] in (1, 2) for c in chans)
    ind = {c["name"] for c in chans if c["type"] == "individual"}
    assert {"bornlupin", "beluga_investment", "hedgehara", "d_ticker"} <= ind


def test_hits_word_boundaries():
    kw = ["won", "Iran", "oil"]
    assert tg_feed.hits("KOREAN WON WEAKENS PAST 1,450", kw) == ["won"]
    assert tg_feed.hits("WE WON'T NEGOTIATE", kw) == []
    assert tg_feed.hits("TOILET PAPER SHORTAGE", kw) == [] and tg_feed.hits("OILS RALLY", kw) == ["oil"]
