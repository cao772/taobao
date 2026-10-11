"""Browser-rendered fixtures exercise price attribution, login gates and provenance."""
import asyncio
import pytest
from playwright.async_api import async_playwright
from multimall.adapters import OBSERVE_JS, product_url, safe_page_url
from multimall.orchestration import search_all_platforms

async def observe(html, platform='jd', mode='products', url='https://search.jd.com/Search?keyword=test'):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.route('**/*', lambda route: route.fulfill(body=html, content_type='text/html; charset=utf-8'))
        await page.goto(url)
        result = await page.evaluate(OBSERVE_JS, {'platform':platform,'mode':mode,'limit':10})
        await browser.close()
        return result


def test_visible_card_price_not_neighbor_ad_or_hidden_product():
    html = '''<span>广告 ￥1</span><div id="J_goodsList">
      <div class="gl-item"><div class="p-name"><a href="https://item.jd.com/123.html?tracking=x"><em>ESP32-S3</em></a></div><div class="p-price">￥139.50</div><div class="p-shop">示例店铺</div></div>
      <div class="gl-item" style="display:none"><div class="p-name"><a href="https://item.jd.com/456.html">隐藏商品</a></div><div class="p-price">￥2</div></div>
      <div class="gl-item"><div class="p-name"><a href="https://item.jd.com.evil.example/123.html">伪域名</a></div><div class="p-price">￥3</div></div></div>'''
    found = asyncio.run(observe(html))
    assert len(found['products']) == 1
    row = found['products'][0]
    assert row['raw_price'] == '139.50'
    assert row['url'] == 'https://item.jd.com/123.html'
    assert row['merchant'] == '示例店铺'
    assert row['evidence']['price_selector'] == '.p-price'


@pytest.mark.parametrize('price', ['￥10 - ￥200', '券后139 原价200', '139起', '月付13.9', '2人团139'])
def test_ambiguous_price_kept_unknown(price):
    html = '<div id="J_goodsList"><div class="gl-item"><div class="p-name"><a href="https://item.jd.com/123.html">ESP32-S3</a></div><div class="p-price">'+price+'</div></div></div>'
    row = asyncio.run(observe(html))['products'][0]
    assert row['raw_price'] is None


def test_visible_login_frame_hides_stale_products():
    html = '''<iframe src="https://login.taobao.com/member/login.jhtml"></iframe><div id="J_goodsList"><div class="gl-item"><div class="p-name"><a href="https://item.jd.com/123.html">旧商品</a></div></div></div>'''
    found = asyncio.run(observe(html))
    assert found['state'] == 'login_required'
    assert found['products'] == []


def test_hidden_login_frame_does_not_block_public_card():
    html = '''<iframe style="display:none" src="https://login.taobao.com/"></iframe><div id="J_goodsList"><div class="gl-item"><div class="p-name"><a href="https://item.jd.com/123.html">ESP32-S3</a></div></div></div>'''
    assert len(asyncio.run(observe(html))['products']) == 1


def test_challenge_and_login_url_classification():
    found = asyncio.run(observe('<title>京东验证</title><p>请完成验证</p>'))
    assert found['state'] == 'verification_required'
    found = asyncio.run(observe('<h1>登录</h1>', url='https://mobile.yangkeduo.com/login.html', platform='pdd'))
    assert found['state'] == 'login_required'


def test_reviews_are_content_only_visible_and_deduplicated():
    html = '''<div class="comment-item"><span>用户昵称</span><p class="comment-con">屏幕有破损，售后不处理</p></div>
      <div class="comment-item" style="display:none"><p class="comment-con">不可见评价</p></div>
      <div class="comment-item"><p class="comment-con">屏幕有破损，售后不处理</p></div>'''
    rows = asyncio.run(observe(html, mode='reviews'))['reviews']
    assert rows == [{'text':'屏幕有破损，售后不处理','selector':'.comment-item .comment-con'}]


def test_non_product_and_sensitive_query_protection():
    assert not product_url('jd','https://order.jd.com/center/list.action')
    assert not product_url('taobao','https://item.taobao.com/login?id=123')
    assert product_url('taobao','https://item.taobao.com/item.htm?id=123')
    safe = safe_page_url('https://passport.jd.com/login?token=secret&pin=account&ReturnUrl=private')
    assert safe == 'https://passport.jd.com/login'


def test_fanout_preserves_restriction_diagnostics():
    async def provider(platform, query, limit):
        return {'status':'login_required','products':[], 'reason':'请登录'}
    found = asyncio.run(search_all_platforms(provider,'ESP32-S3',['taobao']))
    assert found['per_platform'][0]['status'] == 'login_required'
    assert found['products'] == []


def test_new_jd_dom_uses_visible_sku_and_split_price():
    html = '''<div class="plugin_goodsCardWrapper" data-sku="123">
      <div class="_goods_title_container_x">AMOLED开发板</div><span class="_price_x">¥<span>137</span><span>.</span><span>50</span></span>
      <span class="_name_x">店铺名称</span></div>'''
    row = asyncio.run(observe(html))['products'][0]
    assert row['raw_price'] == '137.50'
    assert row['url'] == 'https://item.jd.com/123.html'


def test_new_taobao_dom_split_price_excludes_sales_badge():
    html = '''<div class="doubleCardWrapper--abc"><a href="https://item.taobao.com/item.htm?id=123"></a>
      <div class="title--x">AMOLED开发板</div><div class="priceWrapper--x"><div class="innerPriceWrapper--x">158<span>\n.11</span></div>优惠后 3000人付款</div><span class="shopNameText--x">店铺名称</span></div>'''
    row = asyncio.run(observe(html,platform='taobao',url='https://s.taobao.com/search?q=test'))['products'][0]
    assert row['raw_price'] == '158.11'
    assert row['merchant'] == '店铺名称'


def test_pdd_unlinked_cards_require_real_navigation_before_offer():
    html = '''<div class="_3glhOBhU"><div class="_3ANzdjkc">AMOLED开发板</div><span class="_3_U04GgA">券后 ¥ 94</span></div>'''
    found = asyncio.run(observe(html,platform='pdd',url='https://mobile.yangkeduo.com/search_result.html'))
    assert found['products'] == []
    assert found['unlinked_products'][0]['raw_price'] == '94'
    assert found['unlinked_products'][0]['url'] is None


def test_secondhand_market_unknown_condition_requires_opt_in():
    from multimall.intelligence import recommend_products
    row = {'platform':'xianyu','title':'AMOLED开发板','url':'https://www.goofish.com/item?id=123', 'displayed_price_yuan':'88','condition':'unknown'}
    assert recommend_products([row])['recommendations'] == []
    assert len(recommend_products([row],include_secondhand=True)['recommendations']) == 1


def test_native_pdd_click_resolves_public_goods_link_and_restores_search():
    from multimall.browser import ReadOnlyBrowser
    async def run():
        async with async_playwright() as pw:
            engine = await pw.chromium.launch(headless=True)
            context = await engine.new_context()
            page = await context.new_page()
            html = '''<div class="_3glhOBhU"><div class="_3ANzdjkc" onclick="location.href='/goods.html?goods_id=123'">AMOLED开发板</div><span class="_3_U04GgA">¥ 99</span></div>'''
            await page.route('**/*', lambda route: route.fulfill(body=html, content_type='text/html; charset=utf-8'))
            await page.goto('https://mobile.yangkeduo.com/search_result.html')
            reader = ReadOnlyBrowser(platform='pdd')
            reader._page, reader._context = page, context
            result = await reader.search('pdd', 'ESP32-S3', 1)
            assert result['products'][0]['url'] == 'https://mobile.yangkeduo.com/goods.html?goods_id=123'
            assert result['products'][0]['displayed_price_yuan'] == '99'
            assert '/search_result.html' in page.url
            await engine.close()
    asyncio.run(run())


def test_current_taobao_reviews_exclude_username_date_and_heading():
    html = '''<div class="Comments--x">用户评价 8<div class="Comment--x"><span>用户昵称 2026-10-08</span><div class="content--x">做工很好，屏幕很清晰。</div></div></div>'''
    rows = asyncio.run(observe(html,platform='taobao',url='https://item.taobao.com/item.htm?id=123',mode='reviews'))['reviews']
    assert len(rows) == 1
    assert rows[0]['text'] == '做工很好，屏幕很清晰。'
