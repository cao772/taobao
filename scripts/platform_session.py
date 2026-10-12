"""Interactive login helper: Enter inspects current page; q closes the session."""
import argparse
import asyncio
import json
from multimall.browser import PlatformBrowserPool
from multimall.core import PLATFORMS

async def run(args):
    pool = PlatformBrowserPool()
    try:
        print(json.dumps(await pool.open_session(args.platform, args.keyword), ensure_ascii=False, indent=2))
        while True:
            command = await asyncio.to_thread(input, '浏览器自行登录/验证后回车读取；q 关闭：')
            if command.strip().lower() == 'q':
                break
            print(json.dumps(await pool.inspect_session(args.platform), ensure_ascii=False, indent=2))
    finally:
        await pool.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('platform', choices=list(PLATFORMS))
    parser.add_argument('--keyword', default='ESP32-S3 AMOLED')
    asyncio.run(run(parser.parse_args()))
