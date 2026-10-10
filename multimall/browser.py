"""Conservative visible-browser reader for human-owned shopping sessions.

No form submission, payment, cart mutation, captcha bypass or cookie extraction.
Only supported shopping domains can be navigated to. Real-page extraction is
best effort: an empty result is not evidence that no product exists.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .core import PLATFORMS, allowlisted_url, make_offer, platform_from_url, search_url

_DOM_EXTRACT = r"""
({platform, limit}) => {
  const prefixes = {
    jd: ['item.jd.com/', 'item.m.jd.com/'],
    taobao: ['item.taobao.com/', 'detail.tmall.com/', 'item.m.taobao.com/'],
    pdd: ['goods.html', 'goods_id=', '/goods/'],
    dewu: ['/product-detail', '/product/'],
    xianyu: ['/item', 'item2.', '/detail'],
    meituan: ['/deal/', '/product/', '/poi/']
  };
  const seen = new Set(), goods = [];
  const allowed = prefixes[platform] || [];
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.href || '';
    if (!href.startsWith('https://') || !allowed.some(p => href.includes(p))) continue;
    if (seen.has(href)) continue;
    const container = a.closest('[class*="item"], [class*="goods"], [class*="product"], li') || a.parentElement;
    const text = ((container && container.innerText) || a.innerText || '').replace(/\s+/g,' ').trim();
    const title = (a.getAttribute('title') || a.innerText || text).replace(/\s+/g,' ').trim().slice(0,180);
    if (!title || title.length < 3) continue;
    const matches = text.match(/[￥¥]\s*\d{1,8}(?:\.\d{1,2})?/g) || [];
    goods.push({ title, url: href, raw_price: matches.length ? matches[0] : null, preview: text.slice(0,250) });
    seen.add(href);
    if (goods.length >= limit) break;
  }
  const body = document.body ? document.body.innerText : '';
  return { title: document.title, url: location.href, items: goods,
    page_excerpt: body.replace(/\s+/g,' ').slice(0,1500) };
}
"""

_DETAIL_EXTRACT = r"""
() => {
  const meta = (key) => document.querySelector('meta[property="' + key + '"], meta[name="' + key + '"]')?.content || '';
  const body = document.body ? document.body.innerText.replace(/\s+/g,' ').slice(0,4000) : '';
  const prices = (body.match(/[￥¥]\s*\d{1,8}(?:\.\d{1,2})?/g) || []).slice(0,8);
  return {
    title: meta('og:title') || document.title,
    url: location.href,
    meta_description: meta('description').slice(0,500),
    meta_price: meta('product:price:amount'),
    meta_image: meta('og:image'),
    candidate_price_texts: prices,
    page_excerpt: body,
  };
}
"""


class ReadOnlyBrowser:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._playwright = None
        self._context = None
        self._page = None

    async def _ensure(self) -> None:
        if self._page is not None and not self._page.is_closed():
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise RuntimeError("缺少 playwright，执行 pip install -e . 和 python -m playwright install chromium") from e
        self._playwright = await async_playwright().start()
        profile_dir = Path(os.environ.get("MULTIMALL_PROFILE_DIR", str(Path.home() / ".multimall-mcp" / "browser-profile"))).expanduser()
        profile_dir.mkdir(parents=True, exist_ok=True)
        headless = os.environ.get("MULTIMALL_HEADLESS", "false").lower() == "true"
        self._context = await self._playwright.chromium.launch_persistent_context(
            str(profile_dir), headless=headless, accept_downloads=False,
            viewport={"width": 1440, "height": 900},
        )
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()

    async def _visit(self, url: str) -> dict[str, Any] | None:
        if not allowlisted_url(url):
            raise ValueError("拒绝访问非电商允许域名或非 HTTPS 地址")
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await self._page.wait_for_timeout(1300)
        except Exception as e:
            return {"status": "navigation_error", "reason": str(e)[:220], "requested_url": url}
        # Also validate the target after redirects. Never read information from an unexpected origin.
        if not allowlisted_url(self._page.url):
            redirected = self._page.url
            await self._page.goto("about:blank")
            return {"status": "unexpected_redirect", "reason": "跳转到非允许域名，已停止读取", "redirect_host": urlparse(redirected).hostname}
        return None

    async def search(self, platform: str, query: str, limit: int = 10) -> dict[str, Any]:
        if platform not in PLATFORMS:
            return {"status": "invalid_platform", "allowed": list(PLATFORMS)}
        limit = min(max(int(limit), 1), 20)
        async with self._lock:
            await self._ensure()
            url = search_url(platform, query)
            error = await self._visit(url)
            if error:
                return error
            result: dict[str, Any] = await self._page.evaluate(_DOM_EXTRACT, {"platform": platform, "limit": limit})
            offers = []
            for obj in result["items"]:
                try:
                    offers.append(make_offer(platform, obj["title"], obj["url"], obj["raw_price"]).to_dict())
                except (ValueError, KeyError):
                    continue
            if platform in ("dewu", "meituan"):
                status = "manual_search_required"
            else:
                status = "observed" if offers else "no_extractable_products"
            return {
                "status": status,
                "platform": platform,
                "query": query,
                "opened_url": self._page.url,
                "products": offers,
                "page_title": result["title"],
                "page_excerpt": result["page_excerpt"] if not offers else "",
                "data_source": "live_visible_browser_not_checkout_verified",
                "notice": "结果取自当前浏览器可见 DOM。为空可能是登录、风控、动态页面或选择器失效，不代表商品不存在。得物/美团需在打开的页面中手动完成检索。",
            }

    async def details(self, url: str) -> dict[str, Any]:
        async with self._lock:
            if not allowlisted_url(url):
                return {"status": "blocked_url", "reason": "非允许 HTTPS 电商域名"}
            await self._ensure()
            error = await self._visit(url)
            if error:
                return error
            detail = await self._page.evaluate(_DETAIL_EXTRACT)
            return {
                "status": "observed",
                "platform": platform_from_url(self._page.url),
                "data_source": "live_visible_browser_not_checkout_verified",
                "data": detail,
                "notice": "candidate_price_texts 为正文中出现的候选价格，不一定是 SKU 实际售价；请复核规格、库存、地区与结算页。",
            }

    async def close(self) -> dict[str, str]:
        async with self._lock:
            if self._context is not None:
                await self._context.close()
            if self._playwright is not None:
                await self._playwright.stop()
            self._context = self._page = self._playwright = None
            return {"status": "closed"}
