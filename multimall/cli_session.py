"""Optional read-only bridge to an existing human-authorized Playwright CLI session.

No session/cookie export. The CLI owns its browser lifetime. Serialized commands
avoid multi-tool races in its active-tab control. Only our allowlisted reads run.
"""
import asyncio
import json
import os
import re
from .core import PLATFORMS

_LOCK = asyncio.Lock()


class CliPage:
    def __init__(self, platform: str):
        self.platform = platform
        self.url = 'about:blank'
        self.session = os.environ['MULTIMALL_PLAYWRIGHT_SESSION']
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', self.session):
            raise ValueError('MULTIMALL_PLAYWRIGHT_SESSION 名称无效')
        self.binary = os.environ.get('MULTIMALL_PLAYWRIGHT_CLI', 'playwright-cli')
        self._known = False

    def is_closed(self):
        return False

    async def _run(self, operation: str):
        hosts = json.dumps(PLATFORMS[self.platform]['hosts'])
        # Select only an existing page of this platform, never an arbitrary user tab.
        code = '''async active => {
          const hosts = HOSTS;
          const matches = p => { try { const u=new URL(p.url()); return u.protocol==='https:' && hosts.some(h=>u.hostname===h || u.hostname.endsWith('.'+h)); } catch (_) { return false; } };
          const page = active.context().pages().find(matches);
          if (!page) return {missing:true};
          const safe = () => {const u=new URL(page.url()); const q=new URLSearchParams(); for(const k of ['id','goods_id','q','keyword','search_key']) if(u.searchParams.has(k)) q.set(k,u.searchParams.get(k).slice(0,120)); return u.origin+u.pathname+(q.size?'?'+q:'');};
          OPERATION
        }'''.replace('HOSTS', hosts).replace('OPERATION', operation)
        async with _LOCK:
            process = await asyncio.create_subprocess_exec(self.binary, '--session', self.session, 'run-code', code,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=40)
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                raise RuntimeError('已授权浏览器会话读取超时') from None
        # Discard CLI tab listings and logs: they may contain login/SSO query data.
        text = stdout.decode(errors='replace')
        match = re.search(r'### Result\s*\n(.*?)\n### ', text, re.S)
        if process.returncode != 0 or not match:
            raise RuntimeError('Playwright CLI 会话不可用；请检查 session 名称及 CLI 安装')
        result = json.loads(match.group(1))
        if result.get('missing'):
            raise RuntimeError('该平台尚无已打开的授权标签页，请先在此浏览器打开平台搜索页')
        self.url = result['url']
        self._known = True
        return result.get('value')

    async def refresh_url(self):
        await self._run('return {url:safe(), value:null};')

    async def goto(self, url, **options):
        await self._run('await page.goto(' + json.dumps(url) + ', {waitUntil:"domcontentloaded",timeout:30000}); return {url:safe(), value:null};')
        return None

    async def evaluate(self, expression, arg=None):
        # Validate after redirects immediately before reading DOM.
        operation = 'if (!matches(page)) return {url:safe(),value:{state:"unexpected_redirect",products:[],reviews:[]}}; const value=await page.evaluate(' + expression + ', ' + json.dumps(arg) + '); return {url:safe(),value};'
        return await self._run(operation)

    async def resolve_card_link(self, row):
        if self.platform != 'pdd' or row['evidence']['card_selector'] != '._3glhOBhU' or row['evidence']['title_selector'] != '._3ANzdjkc':
            return None
        data = json.dumps({'index': row['card_index'], 'title': row['title']})
        operation = '''const data=DATA;
          const card=page.locator('._3glhOBhU').nth(data.index);
          const title=card.locator('._3ANzdjkc');
          if ((await title.innerText()).replace(/\\s+/g,' ').trim().slice(0,240)!==data.title) return {url:safe(),value:null};
          const before=page.url(), originalSafe=safe(), tabs=page.context().pages();
          let target;
          try {
            await title.click({timeout:5000});
            for(let i=0;i<8;i++) { await page.waitForTimeout(500); target=page.context().pages().find(p=>!tabs.includes(p)) || page; if(target.url()!==before && target.url()!=='about:blank') break; }
            const u=new URL(target.url());
            const id=u.searchParams.get('goods_id');
            const valid=u.protocol==='https:' && hosts.some(h=>u.hostname===h||u.hostname.endsWith('.'+h)) && u.pathname.endsWith('/goods.html') && /^\\d+$/.test(id||'');
            const value=valid ? u.origin+u.pathname+'?goods_id='+id : null;
            return {url:originalSafe,value};
          } finally {
            if (target && target!==page) await target.close();
            else if(page.url()!==before) await page.goBack({waitUntil:'domcontentloaded',timeout:15000});
          }'''.replace('DATA', data)
        return await self._run(operation)
