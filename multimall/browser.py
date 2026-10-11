"""Read-only, persistent shopping sessions. Humans handle login and verification."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .adapters import DETAIL_JS, OBSERVE_JS, product_url, safe_page_url
from .core import PLATFORMS, allowlisted_url, make_offer, platform_from_url, search_url

_MESSAGES = {
    'login_required': '请在专用浏览器自行登录，再调用 inspect_platform_session 或重新搜索。',
    'verification_required': '平台要求人工验证；请在浏览器处理后重试，不自动处理验证码。',
    'loading': '页面仍在加载；可稍后读取当前会话，不代表无商品。',
    'no_extractable_products': '未找到支持的可见商品卡片；可能是页面变化或平台限制，不代表无货。',
    'manual_search_required': '该平台暂需用户在浏览器内完成检索，尚无已验证的商品适配器。',
}


class ReadOnlyBrowser:
    def __init__(self, profile_dir: str | None = None, platform: str | None = None) -> None:
        self._platform = platform
        self._profile_dir = profile_dir
        self._lock = asyncio.Lock()
        self._playwright = self._context = self._page = None

    async def _ensure(self) -> None:
        if self._page is not None and not self._page.is_closed():
            return
        if self._context is not None or self._playwright is not None:
            await self._cleanup()
        if os.environ.get('MULTIMALL_PLAYWRIGHT_SESSION'):
            from .cli_session import CliPage
            self._page = CliPage(self._platform)
            await self._page.refresh_url()
            return
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        root = self._profile_dir or os.environ.get('MULTIMALL_PROFILE_DIR', str(Path.home()/'.multimall-mcp/browser-profile'))
        profile = Path(root).expanduser()
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        options = dict(headless=os.environ.get('MULTIMALL_HEADLESS', 'false').lower() == 'true',
                       accept_downloads=False, viewport={'width': 1440, 'height': 900})
        channel = os.environ.get('MULTIMALL_BROWSER_CHANNEL')
        if channel:
            if channel not in ('chrome', 'msedge', 'chromium'):
                await self._cleanup()
                raise ValueError('MULTIMALL_BROWSER_CHANNEL 仅支持 chrome/msedge/chromium')
            options['channel'] = channel
        proxy = os.environ.get('MULTIMALL_PROXY_SERVER')
        if proxy:
            options['proxy'] = {'server': proxy}
        try:
            self._context = await self._playwright.chromium.launch_persistent_context(str(profile), **options)
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        except Exception:
            await self._cleanup()
            raise RuntimeError('专用浏览器启动失败：检查浏览器安装、channel 和 Profile 是否被其他进程占用。') from None

    async def _visit(self, url: str, reuse_current: bool = False) -> dict[str, Any] | None:
        if not allowlisted_url(url):
            raise ValueError('拒绝非电商允许域名或非 HTTPS 地址')
        if reuse_current:
            # CLI URLs are cached; refresh only metadata, never reload a manually verified page.
            if hasattr(self._page, 'refresh_url'):
                await self._page.refresh_url()
            if allowlisted_url(self._page.url) and safe_page_url(self._page.url) == safe_page_url(url):
                return None
        try:
            response = await self._page.goto(url, wait_until='domcontentloaded', timeout=30000)
        except Exception:
            return {'status': 'navigation_error', 'reason': '平台页面导航失败或超时；请检查网络并在浏览器确认。', 'requested_url': safe_page_url(url)}
        if not allowlisted_url(self._page.url):
            host = urlparse(self._page.url).hostname
            # Login may legitimately involve external SSO; leave it for the human,
            # but never extract its DOM or URL parameters.
            return {'status': 'unexpected_redirect', 'reason': '跳转到未支持的登录/外部域名，停止读取。', 'redirect_host': host}
        if response and response.status in (401, 403, 429):
            return {'status': 'verification_required', 'reason': '平台拒绝访问或限流；请人工处理。'}
        return None

    async def _observe(self, platform: str, limit: int = 10, mode: str = 'products', wait: bool = True) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + (12 if wait else 0)
        while True:
            if not allowlisted_url(self._page.url) or platform_from_url(self._page.url) != platform:
                return {'state': 'unexpected_redirect', 'products': [], 'reviews': [], 'reason': '当前页面不在指定平台允许域名内，未读取。'}
            result = await self._page.evaluate(OBSERVE_JS, {'platform': platform, 'limit': limit, 'mode': mode})
            pending = result['state'] in ('loading', 'no_extractable_products') if mode == 'products' else result['state'] == 'ready' and not result['reviews']
            if not pending or asyncio.get_running_loop().time() >= deadline:
                return result
            await asyncio.sleep(0.5)

    def _offers(self, platform: str, result: dict[str, Any]) -> list[dict[str, Any]]:
        offers = []
        for item in result.get('products', []):
            if not product_url(platform, item['url']):
                continue
            offer = make_offer(platform, item['title'], item['url'], item['raw_price'],
                               merchant=item['merchant'], condition=item['condition']).to_dict()
            offer['raw_price_text'] = item['raw_price_text']
            offer['evidence'] = item['evidence']
            offers.append(offer)
        return offers

    async def _session_result(self, platform: str, limit: int = 10, wait: bool = True) -> dict[str, Any]:
        result = await self._observe(platform, limit, wait=wait)
        state = result['state']
        if platform == 'pdd' and state == 'ready':
            for row in result.get('unlinked_products', []):
                link = await self._resolve_pdd_card(row)
                if link and product_url('pdd', link):
                    row['url'] = link
                    row['evidence']['link_source'] = 'visible_title_click_navigation'
                    result['products'].append(row)
        offers = self._offers(platform, result) if state in ('ready', 'no_extractable_products') else []
        if platform in ('dewu', 'meituan') and state in ('ready', 'no_extractable_products'):
            state = 'manual_search_required'
        elif offers:
            state = 'observed'
        elif state == 'ready':
            state = 'no_extractable_products'
        return {'status': state, 'platform': platform, 'products': offers,
                'opened_url': safe_page_url(self._page.url), 'page_title': result.get('page_title', ''),
                'adapter': result.get('adapter'), 'data_source': 'live_visible_browser_not_checkout_verified',
                'reason': result.get('reason') or _MESSAGES.get(state, ''),
                'notice': '仅包含当前页面可见商品字段；未知价格保持 null，展示价未经结算验证。'}

    async def _resolve_pdd_card(self, row: dict[str, Any]) -> str | None:
        if row['evidence']['card_selector'] != '._3glhOBhU' or row['evidence']['title_selector'] != '._3ANzdjkc':
            return None
        if hasattr(self._page, 'resolve_card_link'):
            return await self._page.resolve_card_link(row)
        original = self._page.url
        old_tabs = list(self._context.pages)
        target = None
        try:
            title = self._page.locator('._3glhOBhU').nth(row['card_index']).locator('._3ANzdjkc')
            if ' '.join((await title.inner_text()).split())[:240] != row['title']:
                return None
            await title.click(timeout=5000)
            for _ in range(8):
                await asyncio.sleep(0.5)
                target = next((p for p in self._context.pages if p not in old_tabs), self._page)
                if target.url != original and target.url != 'about:blank':
                    break
            return safe_page_url(target.url) if target and product_url('pdd', target.url) else None
        except Exception:
            return None
        finally:
            if target and target is not self._page:
                await target.close()
            elif self._page.url != original:
                await self._page.go_back(wait_until='domcontentloaded', timeout=15000)

    async def search(self, platform: str, query: str, limit: int = 10) -> dict[str, Any]:
        if platform not in PLATFORMS:
            return {'status': 'invalid_platform', 'allowed': list(PLATFORMS)}
        url = search_url(platform, query)
        if not 1 <= limit <= 20:
            return {'status': 'invalid_input', 'reason': 'limit 必须为 1-20'}
        async with self._lock:
            await self._ensure()
            error = await self._visit(url)
            if error:
                return {**error, 'platform': platform, 'products': []}
            return {**await self._session_result(platform, limit), 'query': query}

    async def open_session(self, platform: str, query: str = '') -> dict[str, Any]:
        url = search_url(platform, query) if query else 'https://' + {
            'taobao': 'www.taobao.com/', 'jd': 'www.jd.com/', 'pdd': 'mobile.yangkeduo.com/',
            'xianyu': 'www.goofish.com/', 'dewu': 'www.dewu.com/', 'meituan': 'www.meituan.com/'}[platform]
        async with self._lock:
            await self._ensure()
            error = await self._visit(url)
            return error or await self._session_result(platform)

    async def inspect_session(self, platform: str, limit: int = 10) -> dict[str, Any]:
        # Deliberately do not launch/navigate: preserve the user's ongoing login.
        async with self._lock:
            if self._page is None or self._page.is_closed():
                return {'status': 'session_not_open', 'platform': platform, 'products': [], 'reason': '先调用 open_platform_session。'}
            return await self._session_result(platform, limit)

    async def details(self, url: str) -> dict[str, Any]:
        platform = platform_from_url(url)
        if not platform or not product_url(platform, url):
            return {'status': 'blocked_url', 'reason': '需要已支持平台的具体商品链接，不读取账户、订单或店铺页。'}
        async with self._lock:
            await self._ensure()
            error = await self._visit(url, reuse_current=True)
            if error:
                return error
            found = await self._observe(platform, mode='detail', wait=False)
            if found['state'] != 'ready':
                return {'status': found['state'], 'reason': _MESSAGES.get(found['state'], ''), 'data': None}
            data = await self._page.evaluate(DETAIL_JS, {'platform': platform})
            if platform == 'jd' and not data['attributes']:
                # Read-only product specifications control; never click SKU/cart/buy controls.
                try:
                    if hasattr(self._page, 'reveal_parameters'):
                        clicked = await self._page.reveal_parameters()
                    else:
                        control = self._page.locator('.parameter').first
                        clicked = bool(await control.count() and await control.is_visible())
                        if clicked:
                            await control.click(timeout=5000)
                            await asyncio.sleep(1.2)
                    if clicked:
                        gate = await self._observe(platform, mode='detail', wait=False)
                        if gate['state'] != 'ready':
                            return {'status':gate['state'], 'data':None}
                        data = await self._page.evaluate(DETAIL_JS, {'platform':platform})
                        data['parameter_control_action'] = 'opened_visible_specs_control'
                except Exception:
                    data['parameter_control_action'] = 'unavailable'
            data['observed_at_utc'] = datetime.now(timezone.utc).isoformat()
            data['url'] = safe_page_url(self._page.url)
            return {'status': 'observed', 'platform': platform, 'data': data,
                    'data_source': 'live_visible_browser_not_checkout_verified',
                    'notice': '可见文本仅为页面证据，不把任意正文金额当作 SKU 售价。'}

    async def visible_reviews(self, url: str, limit: int = 20) -> dict[str, Any]:
        platform = platform_from_url(url)
        if not platform or not product_url(platform, url):
            return {'status': 'blocked_url', 'reviews': [], 'reason': '需要具体商品链接。'}
        if not 1 <= limit <= 50:
            return {'status': 'invalid_input', 'reviews': [], 'reason': 'limit 必须是 1-50'}
        async with self._lock:
            await self._ensure()
            error = await self._visit(url, reuse_current=True)
            if error:
                return {**error, 'reviews': []}
            found = await self._observe(platform, limit, mode='reviews')
            rows = [{'text': r['text'], 'source_url': safe_page_url(self._page.url),
                     'extraction_selector': r['selector'], 'verified_purchase': None,
                     'review_date_text': r.get('review_date_text', ''),
                     'observed_at_utc': datetime.now(timezone.utc).isoformat()} for r in found.get('reviews', [])]
            status = found['state'] if found['state'] != 'ready' else ('observed' if rows else 'no_visible_reviews')
            return {'status': status, 'platform': platform, 'reviews': rows, 'review_count': len(rows),
                    'page_url': safe_page_url(self._page.url), 'reason': _MESSAGES.get(status, ''),
                    'provenance': 'visible_dom_only_not_independently_verified',
                    'caveat': '仅当前渲染的评价正文；未读取分页/折叠评论，无法核实真实购买，缺失不代表没有差评。'}

    async def _cleanup(self) -> None:
        try:
            if self._context is not None:
                await self._context.close()
        finally:
            if self._playwright is not None:
                await self._playwright.stop()
            self._context = self._page = self._playwright = None

    async def close(self) -> dict[str, str]:
        async with self._lock:
            borrowed = hasattr(self._page, 'session')
            await self._cleanup()
            return {'status': 'released_external_session' if borrowed else 'closed'}


class PlatformBrowserPool:
    """One persistent profile and serialized page operations per platform."""
    def __init__(self) -> None:
        self._browsers: dict[str, ReadOnlyBrowser] = {}
        self._mutex = asyncio.Lock()
        self._root = Path(os.environ.get('MULTIMALL_PROFILE_DIR', str(Path.home()/'.multimall-mcp/browser-profiles'))).expanduser()

    async def _browser(self, platform: str) -> ReadOnlyBrowser:
        if platform not in PLATFORMS:
            raise ValueError('未支持的平台')
        async with self._mutex:
            if platform not in self._browsers:
                self._browsers[platform] = ReadOnlyBrowser(str(self._root/platform), platform=platform)
            return self._browsers[platform]

    async def search(self, platform: str, query: str, limit: int = 10) -> dict[str, Any]:
        return await (await self._browser(platform)).search(platform, query, limit)

    async def open_session(self, platform: str, query: str = '') -> dict[str, Any]:
        return await (await self._browser(platform)).open_session(platform, query)

    async def inspect_session(self, platform: str, limit: int = 10) -> dict[str, Any]:
        if not 1 <= limit <= 20:
            return {'status': 'invalid_input', 'reason': 'limit 必须为 1-20'}
        return await (await self._browser(platform)).inspect_session(platform, limit)

    async def details(self, url: str) -> dict[str, Any]:
        p = platform_from_url(url)
        if p is None or not allowlisted_url(url):
            return {'status': 'blocked_url', 'reason': '不在电商允许列表中'}
        return await (await self._browser(p)).details(url)

    async def visible_reviews(self, url: str, limit: int = 20) -> dict[str, Any]:
        p = platform_from_url(url)
        if p is None or not allowlisted_url(url):
            return {'status': 'blocked_url', 'reviews': [], 'reason': 'URL 不在允许列表'}
        return await (await self._browser(p)).visible_reviews(url, limit)

    async def close(self) -> dict[str, Any]:
        async with self._mutex:
            browsers = list(self._browsers.values())
            self._browsers.clear()
        results = await asyncio.gather(*(b.close() for b in browsers), return_exceptions=True)
        return {'status': 'released_external_session' if results and all(isinstance(r, dict) and r.get('status') == 'released_external_session' for r in results) else ('closed' if all(isinstance(r, dict) for r in results) else 'partial'),
                'browsers_closed': sum(isinstance(r, dict) and r.get('status') == 'closed' for r in results),
                'external_sessions_released': sum(isinstance(r, dict) and r.get('status') == 'released_external_session' for r in results)}
