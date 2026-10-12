"""Real MCP stdio smoke calls; only save counts/states, no login data/page dumps."""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

def unpack(reply):
    if reply.isError:
        raise RuntimeError('MCP 工具返回错误，停止验收，不能记作成功')
    return reply.structuredContent or json.loads(reply.content[0].text)

async def run(args):
    parameters = StdioServerParameters(command=sys.executable, args=['-m', 'multimall.server'], env=dict(os.environ))
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = [t.name for t in (await session.list_tools()).tools]
            observations = []
            try:
                for platform in args.platforms:
                    data = unpack(await session.call_tool('search_products', {'platform': platform, 'keyword': args.keyword, 'limit': 5}))
                    products = data.get('products', [])
                    result = {'platform': platform, 'status': data.get('status'),
                              'product_count': len(products), 'price_count': sum(p.get('displayed_price_yuan') is not None for p in products),
                              'adapter': data.get('adapter'), 'reason': data.get('reason', '')}
                    if products:
                        evidence = unpack(await session.call_tool('get_visible_reviews', {'product_url': products[0]['url'], 'limit': 5}))
                        result.update(review_status=evidence['status'], review_count=evidence.get('review_count', 0))
                    observations.append(result)
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                targeted_reviews = []
                for url in args.review_url:
                    evidence = unpack(await session.call_tool('get_visible_reviews', {'product_url': url, 'limit': 5}))
                    targeted_reviews.append({'product_url': url, 'status': evidence['status'], 'review_count': evidence.get('review_count', 0), 'quality_score': evidence['summary']['quality_score']})
                research = unpack(await session.call_tool('research_purchase', {'keyword': args.keyword, 'platforms_json': json.dumps(args.platforms), 'include_secondhand': True, 'budget_yuan': 200}))
                research_summary = {'status': research['status'], 'shortlist_count': len(research['shortlist']),
                                    'priced_shortlist_count': sum(i.get('displayed_price_yuan') is not None for i in research['shortlist'])}
            finally:
                cleanup = unpack(await session.call_tool('close_browser', {}))
            report = {'observed_at_utc': datetime.now(timezone.utc).isoformat(), 'keyword': args.keyword,
                      'tool_count': len(names), 'platforms': observations, 'targeted_reviews': targeted_reviews, 'research': research_summary, 'cleanup': cleanup, 'checkout_verified': False}
            if args.output:
                Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
            print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--platforms', nargs='+', default=['taobao','jd','pdd','xianyu'])
    parser.add_argument('--keyword', default='ESP32-S3 AMOLED')
    parser.add_argument('--output')
    parser.add_argument('--review-url', action='append', default=[])
    asyncio.run(run(parser.parse_args()))
