# MultiMall MCP｜跨平台智能选品

Codex / Hermes → MCP stdio → 平台可见网页 → 搜索、同款候选、价格比较、评价证据与人工购物审核。

**2026-10-11 状态**：开发分支已经接入淘宝/天猫、京东、拼多多、闲鱼的用户授权网页商品数据。真实登录会话的验收记录见 [实站验收](docs/live-acceptance-2026-10-11.md)。得物、美团保留人工检索入口。官方联盟 API 未配置；评论覆盖、最终结算价和客户端产品级联调不能视为已全部完成。代码继续保留在 Draft PR #2，未合并 main。

## 使用

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
.venv/bin/python -m multimall.server
```

注册 MCP 的配置见 `examples/codex-config.toml` 和 `examples/hermes-config.yaml`；替换为本机绝对路径。每客户端使用独立 Profile 根目录。默认打开可见的专用浏览器，用户自行扫码登录，不传密码或 Cookie。

1. 调用 `open_platform_session(platform="taobao", keyword="ESP32-S3 AMOLED")` 打开平台，用户自行登录。
2. 调用 `inspect_platform_session(platform="taobao")` 读取当前页，不刷新登录窗口。京东、拼多多、闲鱼同理。
3. 调用 `research_purchase` 完成多平台搜索与待复核候选列表。

```json
{
  "keyword": "ESP32-S3 AMOLED开发板",
  "budget_yuan": 200,
  "platforms_json": "[\"taobao\",\"jd\",\"pdd\",\"xianyu\"]",
  "include_secondhand": true,
  "per_platform_limit": 5,
  "inspect_reviews_top_k": 2,
  "inspect_details_top_k": 3
}
```

Issue #3 的参数、SKU、评论证据及客户端迭代说明见 [本轮实现](docs/issue-3-implementation.md)。一次研究默认检查前三个候选详情、前两个评价区；显式配件/数字资源标题会从开发板推荐中剔除。

完整会话说明、可选的现有 Playwright CLI 会话复用、真实 MCP 复验脚本见 [接入说明](docs/live-integration.md)。不设置 CLI 会话变量时直接用 Python Playwright。

## 14 个工具

- 平台与会话：`list_platforms`、`open_platform_session`、`inspect_platform_session`、`close_browser`。
- 实际网页读取：`search_products`、`search_all_platforms`、`get_product_detail`、`get_visible_reviews`。
- 选品分析：`match_same_products`、`analyze_product_reviews`、`compare_products`、`recommend_best_products`、`research_purchase`。
- 人工审核：`prepare_purchase_review`。

相对上一轮的 12 个工具，新增专用会话打开和当前页面读取两个工具。搜索结果包含真实商品地址、展示价、原始价格文字、时间及字段选择器。页面登录、人工验证、加载和提取受限分别报告，不把空结果当成无货。

## 数据与安全边界

仅按明确品牌、型号、规格、新旧状态分组同款候选；缺失字段保持未知。闲鱼需要显式允许二手候选，商家宣传不等于已核实信誉。缺失评论不补造质量分。展示价可能依赖优惠资格、地区或 SKU，范围/多金额价格保持 null；最终付款价仍需用户核实。

只读取授权可见网页，不导出 Cookie、读取私有页面状态、绕验证码或伪装浏览器指纹。不加购、不提交订单、不付款。凭据、Profile、浏览器原始日志及本地输出不提交进仓库。

## 项目入口

- [代码与 Draft PR #2](https://github.com/cao772/taobao/pull/2)
- [技术方案](https://docs.google.com/document/d/15PwWMW4HzU8YqvYxVM0EE3kd9uF2sPd2_GJqi4iX37U/edit)
- [Notion 记录](https://app.notion.com/p/3f57bbed13528141853cd47e2f1b2238)

本轮更新范围为代码与仓库内验收记录，外部文档并未自动同步。
