# MultiMall MCP｜跨平台 AI 购物工具

**项目定位**：通过标准 MCP 工具，让 Codex、Hermes Agent 等智能体调用淘宝/天猫、京东、拼多多、得物、闲鱼、美团的商品搜索、详情查看、比价与购物审核能力。

> 2026-10-10 状态：v0.1 可运行的技术骨架已在本次对话生成，六平台真实 API 并未接入，浏览器抓取的可用性未做全平台验证，不支持加购、提交订单和付款。计划功能不等于已完成。禁止编造价格。

## 技术路线
Codex / Hermes → MultiMall MCP (Python, stdio) → Search/Detail/Compare/Review → Provider Adapters → 合规官方 API + 授权可见浏览器。

## 已实现的基础工具（v0.1）
- `list_platforms`：平台能力、未连接状态。
- `search_products`：只读浏览器候选搜索；若失败，明确返回需要人工搜索。
- `get_product_detail`：白名单站点页面观察。
- `compare_products`：对已观察价格排序/过滤，不推测真实结算价。
- `prepare_purchase_review`：产生人工购物审核单。
- `close_browser`：关闭专用浏览器。

## v0.2 智能选品引擎（feature/smart-shopping-engine 开发分支）

新增 6 个 MCP 工具：

- `search_all_platforms`：并发搜索多个平台，逐站记录成功/受限/失败，不将空结果当作无货；默认淘宝、京东、拼多多，传入平台列表可包含得物、闲鱼、美团。
- `match_same_products`：**仅按显式品牌、型号、规格、新旧状态**划分同款候选组，未提供身份字段的结果不强行合并。
- `analyze_product_reviews`：仅分析已取得的真实评论片段，报告出现的故障、假货疑虑、售后等信号，**不伪造产品质量分**。
- `recommend_best_products`：基于展示价与可选运费/优惠数据给出待复核候选，不把低价称为最高质量。
- `research_purchase`：一次调用搜索 → 汇总每平台覆盖状态 → 保守的 TOP 3 候选；可选 `inspect_reviews_top_k=1..3` 尝试读取候选商品页可见评价。
- `get_visible_reviews`：读取当前商品页 **确实渲染的疑似评价片段**（可能读不到），附页面地址/选择器/证据局限，并调用评论风险摘要。

重要：此版本主要完成可运行的编排、接口和证据链；平台网页可能拒绝浏览器读取，商家真实评分、用户评价抓取、官方联盟 API 和支付接口**尚未打通**。工具会明确返回受限状态，而不是伪造价格或评分。

### Codex / Hermes 调用示例

向 MCP 工具 `research_purchase` 输入：

```json
{
  "keyword": "ESP32-S3 1.75 AMOLED N16R8",
  "budget_yuan": 200,
  "platforms_json": "[\\"taobao\\",\\"jd\\",\\"pdd\\",\\"xianyu\\"]",
  "include_secondhand": true,
  "per_platform_limit": 8,
  "inspect_reviews_top_k": 2
}
```

结果包括 `discovery.per_platform` 平台结果、`shortlist` 待核实商品、可选的 `review_summary` 与 `recommendation_analysis` 的排除原因。仅展示原始观察所得价格，不承诺该价格可结算。

对用户/Agent 已核对的显式 `brand/model/specification/condition` 字段调用 `match_same_products` 才有严格同款候选分组；若网页未提供这些字段，请标记 `unmatched` 并让用户补充或者获取可验证的产品参数。评论工具 `analyze_product_reviews` 需要由可追溯来源提供评论片段，不会自动制造评价。

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
