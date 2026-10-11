"""End-to-end MCP stdio handshake against the actual packaged server."""
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_initialize_discovery_and_safe_call():
    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "multimall.server"],
            env=dict(os.environ),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert {
                    "list_platforms", "search_products", "get_product_detail",
                    "compare_products", "prepare_purchase_review", "close_browser",
                    "search_all_platforms", "match_same_products",
                    "analyze_product_reviews", "recommend_best_products", "research_purchase", "get_visible_reviews",
                    "open_platform_session", "inspect_platform_session",
                } <= names
                assert len(names) == 14
                response = await session.call_tool("list_platforms", {})
                assert not response.isError
                assert "taobao" in str(response.content)
    asyncio.run(run())
