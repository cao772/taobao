# MultiMall MCP｜跨平台 AI 购物工具

**项目定位**：通过标准 MCP 工具，让 Codex、Hermes Agent 等智能体调用淘宝/天猫、京东、拼多多、得物、闲鱼、美团的商品搜索、详情查看、比价与购物审核能力。

> 2026-10-10 状态：v0.1 可运行的技术骨架已在本次对话生成，六平台真实 API 并未接入，浏览器抓取的可用性未做全平台验证，不支持加购、提交订单和付款。计划功能不等于已完成。禁止编造价格。

## 技术路线
Codex / Hermes → MultiMall MCP (Python, stdio) → Search/Detail/Compare/Review → Provider Adapters → 合规官方 API + 授权可见浏览器。

## 已实现的 v0.1 工具
- `list_platforms`：平台能力、未连接状态。
- `search_products`：只读浏览器候选搜索；若失败，明确返回需要人工搜索。
- `get_product_detail`：白名单站点页面观察。
- `compare_products`：对已观察价格排序/过滤，不推测真实结算价。
- `prepare_purchase_review`：产生人工购物审核单。
- `close_browser`：关闭专用浏览器。

## 安全原则
只读优先；不处理验证码、Cookie 导出、账号密码或绕风控操作；浏览器数据作为不可信输入；所有订单提交和支付必须单独合规许可与用户审批。

## 运行方法（v0.1 代码即将同步）
```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
.venv/bin/python -m multimall.server
```
参见后续代码及 `examples/codex-config.toml`、`examples/hermes-config.yaml`。

## Roadmap
1. 完成源码同步、MCP handshake 实测、CI。
2. 三个联盟 API 适配器：淘宝、京东、拼多多。
3. 得物/闲鱼二手与潮品分析、美团城市/门店/套餐。
4. 同款识别、券后价验证、历史价、风险提示。
5. 人工确认的加购与结算审批；默认禁止自动付款。

**三端事实源**：GitHub 保存代码/Issue/测试；Google Drive 保存发行包/交付文档；Notion 保存项目记忆/需求/状态。

工程是独立商品购物 MCP，不属于广州局九项目。
