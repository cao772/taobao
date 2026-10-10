from multimall.core import (
    PLATFORMS, allowlisted_url, compare_offers, make_offer, parse_price,
    platform_from_url, search_url,
)


def test_six_platforms():
    assert set(PLATFORMS) == {"taobao", "jd", "pdd", "dewu", "xianyu", "meituan"}


def test_allowed_domains_and_unsafe_urls():
    assert allowlisted_url("https://item.jd.com/123.html")
    assert allowlisted_url("https://foo.taobao.com/item.htm")
    assert allowlisted_url("https://www.goofish.com/item?id=2")
    for bad in ["http://item.jd.com/a", "https://jd.com.evil.net/a", "https://eviljd.com/a",
                "file:///etc/passwd", "https://user:pass@jd.com/a", "https://127.0.0.1/a"]:
        assert not allowlisted_url(bad)


def test_search_urls():
    assert "%E8%8B%B9%E6%9E%9C" in search_url("jd", "苹果")
    assert search_url("meituan", "奶茶").startswith("https://www.meituan.com")


def test_prices():
    assert str(parse_price("券后 ¥39.90")) == "39.90"
    assert str(parse_price("¥1,299.00")) == "1299.00"
    assert parse_price("起") is None
    assert parse_price("-1") is None
    assert parse_price("¥0") is None


def test_offer_provenance():
    item = make_offer("jd", "ESP32-S3", "https://item.jd.com/123.html", "¥78.80")
    assert item.price_status == "unverified_display"
    assert item.displayed_price_yuan == "78.80"
    assert item.platform == platform_from_url(item.url)


def test_comparison_and_used_gate():
    goods = [
        {"platform": "jd", "title": "新品", "url": "https://item.jd.com/1.html", "price": "¥90", "condition": "new"},
        {"platform": "xianyu", "title": "二手", "url": "https://www.goofish.com/item?id=1", "price": "¥50", "condition": "used"},
    ]
    result = compare_offers(goods, budget_yuan=100)
    assert result["offers"][0]["platform"] == "jd"
    assert not result["offers"][1]["eligible"]
    assert compare_offers(goods, budget_yuan=100, include_secondhand=True)["offers"][0]["platform"] == "xianyu"


def test_meituan_location_gate():
    item = {"platform":"meituan", "title":"套餐", "url":"https://www.meituan.com/deal/12", "price": 60}
    assert not compare_offers([item])["offers"][0]["eligible"]
    assert compare_offers([item], location="广州")["offers"][0]["eligible"]


def test_no_unverified_domains_in_comparison():
    result = compare_offers([{"platform":"jd", "title":"item", "url":"https://evil.com/", "price": 60}])
    assert result["errors"]
    assert result["offers"] == []
