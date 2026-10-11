# 真实平台接入与复验

本轮接入的是用户授权的可见网页，不是官方联盟 API。价格、商家名称、商品地址均从实际渲染的商品卡片取得；接口凭证未配置，`api_connected` 仍为 false。未知规格、新旧状态、运费、最终应付价及质量分不会补造。

## 两种会话入口

默认使用每平台独立、持久化的专用浏览器 Profile。调用 `open_platform_session(platform, keyword)` 后用户自行登录，再调用 `inspect_platform_session(platform)` 读取当前页面，不刷新、不重开窗口。后续 `search_products`、并发搜索和 `research_purchase` 共用这些平台适配器。两个客户端应各用独立 Profile 根目录，避免同一 Profile 同时被占用。

本次用户已登录 Playwright CLI 的多标签会话，所以增加可选的 CLI 会话桥接，直接读取已授权标签页，不复制或导出 Cookie。注册示例见 `examples/codex-cli-session.toml`。设置：

```sh
export MULTIMALL_PLAYWRIGHT_SESSION=multimall-live
# 若 CLI 不在 PATH，可指向已安装 CLI 或 Playwright 技能的 wrapper。
export MULTIMALL_PLAYWRIGHT_CLI=/absolute/path/to/playwright-cli
.venv/bin/python scripts/live_smoke.py --output output/live-smoke.json
```

CLI 会话中需已打开对应平台标签页；它的生命周期由 CLI 管理。`close_browser` 只释放借用会话，不关闭用户窗口。该桥接是可选项；不设置这些变量时直接使用 Python Playwright。CLI 输出仅解析工具结果，丢弃其他标签页列表，避免 SSO 参数进入 MCP 回包。

持久化会话参数依据 [Playwright 官方 BrowserType 文档](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context)。

默认安装：

```sh
uv venv --python 3.12
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
# 或复用本机 Chrome：MULTIMALL_BROWSER_CHANNEL=chrome
.venv/bin/python scripts/platform_session.py taobao --keyword 'ESP32-S3 AMOLED'
```

交互脚本读取后输入 q 关闭，登录保留在本机专用 Profile 中。MCP 注册示例位于 examples；本地安装必须使用绝对路径。当前共 14 个工具，新增会话打开和当前页面读取两个工具。

## 提取规则与局限

- 淘宝：支持当前 doubleCardWrapper 卡片，分开读取标题、价格整数/小数和店铺名称；保留原始价格文字与选择器。
- 京东：支持传统 gl-item 与当前 plugin_goodsCardWrapper；当前卡片 DOM 的 data-sku 生成商品地址，价格来自价格元素，不能把销量、广告、券门槛或原价算成售价。
- 拼多多：当前移动网页为点击式卡片；只点击可见商品标题取得 goods_id，回到原搜索页。标题变化或地址未取得时不生成商品记录，不读取 React 内部状态或私有接口。最多处理请求数量（1–20）个当前卡片。
- 闲鱼：读取可见 feeds-item 卡片；不把地区或“信用极好”等宣传当作商家身份或评分。平台属于二手市场，即便成色 unknown 也需要 include_secondhand=true 才进入候选。
- 得物、美团：保留原六平台入口与明确受限状态；本轮没有完成可自动提取的实站搜索适配。
- 评价：只读取当前已渲染、平台选择器定位到的评价正文。未读到时返回 no_visible_reviews；登录、验证码和限流单独返回状态，不输出虚构评论、评分或全站覆盖率。

可识别的券后展示价不保证所有账户可享；范围价、月付、多个金额保持 null。页面布局变化可能使适配器失效；空提取不代表无货。全流程不执行加购、提交订单或支付。

## 证据分类

`tests/test_live_adapters.py` 是 Chromium 实际渲染的离线 DOM 样例测试，用于防止字段错配、隐藏元素、伪域名和状态误判；它不证明平台全站可用。

`scripts/live_smoke.py` 通过真实 MCP stdio 初始化、发现工具并调用搜索、评价和研究链路。仅落盘平台状态、商品/价格/评价数量和时间，避免归档账号信息或登录参数。本次实站结果见同目录的验收记录。
