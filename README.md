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

## 安装、测试和运行（v0.1 已提交）
```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
.venv/bin/python -m multimall.server
```
Codex 与 Hermes 注册配置见 `examples/codex-config.toml`、`examples/hermes-config.yaml`。首次运行需要安装浏览器；两客户端使用独立持久化浏览器配置目录。

## Roadmap
1. 已提交 v0.1 源码与 CI 定义；下一步核验 CI 和 Codex/Hermes 的实际 MCP handshake。
2. 三个联盟 API 适配器：淘宝、京东、拼多多。
3. 得物/闲鱼二手与潮品分析、美团城市/门店/套餐。
4. 同款识别、券后价验证、历史价、风险提示。
5. 人工确认的加购与结算审批；默认禁止自动付款。

**三端事实源**：
- GitHub 代码与研发任务：[taobao](https://github.com/cao772/taobao) / [Issue #1](https://github.com/cao772/taobao/issues/1)
- Google Drive：[项目文件夹](https://drive.google.com/drive/folders/1ultO67LwVKCvqV60Ss765Pq2YVMgaD9v) / [技术方案](https://docs.google.com/document/d/15PwWMW4HzU8YqvYxVM0EE3kd9uF2sPd2_GJqi4iX37U/edit)
- Notion：[项目状态与架构](https://app.notion.com/p/3f57bbed13528141853cd47e2f1b2238?pvs=204)

注：Google Drive 当前仅已归档技术方案，ZIP 包仍需单独上传验收。

工程是独立商品购物 MCP，不属于广州局九项目。
