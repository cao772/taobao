"""Preserve human verification and expanded product panels on the current page."""
import asyncio

from multimall.browser import ReadOnlyBrowser


class ProductPage:
    def __init__(self, url):
        self.url = url
        self.visits = []
        self.metadata_refreshes = 0

    def is_closed(self):
        return False

    async def refresh_url(self):
        self.metadata_refreshes += 1

    async def goto(self, url, **kwargs):
        self.visits.append(url)
        self.url = url

    async def evaluate(self, expression, arg):
        if arg.get('mode'):
            return {'state':'ready', 'reviews':[{'text':'屏幕坏了，无法使用', 'selector':'.review-content'}]}
        return {'attributes':{}, 'parameters':[{'text':'示例参数'}], 'sku_options':[], 'selected_specification':''}


def test_details_then_reviews_do_not_reload_verified_current_product():
    async def run():
        url = 'https://item.taobao.com/item.htm?id=123'
        reader = ReadOnlyBrowser(platform='taobao')
        page = ProductPage(url + '&tracking=discarded')
        reader._page = page
        assert (await reader.details(url))['status'] == 'observed'
        assert (await reader.visible_reviews(url))['review_count'] == 1
        assert page.visits == []
        assert page.metadata_refreshes == 2
    asyncio.run(run())


def test_different_product_still_navigates_and_restricted_page_still_stops():
    async def run():
        class RestrictedPage(ProductPage):
            async def evaluate(self, expression, arg):
                return {'state':'verification_required', 'reviews':[]}
        reader = ReadOnlyBrowser(platform='taobao')
        page = RestrictedPage('https://item.taobao.com/item.htm?id=123')
        reader._page = page
        target = 'https://item.taobao.com/item.htm?id=456'
        assert (await reader.details(target))['status'] == 'verification_required'
        assert page.visits == [target]
        assert (await reader.visible_reviews(target))['status'] == 'verification_required'
        assert page.visits == [target]
    asyncio.run(run())


def test_delayed_product_dom_is_read_without_another_navigation():
    async def run():
        class DelayedPage(ProductPage):
            reads=0
            async def evaluate(self, expression, arg):
                if arg.get('mode'):
                    return {'state':'ready','reviews':[]}
                self.reads+=1
                return {'attributes':{},'parameters':[] if self.reads==1 else [{'text':'型号 M185'}],'sku_options':[]}
        reader=ReadOnlyBrowser(platform='pdd')
        page=DelayedPage('https://mobile.yangkeduo.com/goods.html?goods_id=123');reader._page=page
        result=await reader.details(page.url)
        assert result['data']['parameters']==[{'text':'型号 M185'}]
        assert page.reads==2
        assert page.visits==[]
    asyncio.run(run())
