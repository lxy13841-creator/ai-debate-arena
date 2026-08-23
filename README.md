# AI 辩论场

一个在本机运行的 AI 自动辩论网页应用。立场生成、正方、反方和客观总结 Agent 都可以自由选择 Kimi 或 DeepSeek。立场生成 Agent 先把自然语言凝练为双方观点，经用户二次确认后，双方依次立论并进入自由交锋；总结 Agent 在每轮双方发言后提取结构化交锋图数据，但不参与辩论或裁决。

## 快速开始

运行要求：Python 3.10 或更高版本。项目只使用 Python 标准库，不需要执行 `pip install`。

1. 下载项目：点击 GitHub 页面上的 **Code → Download ZIP** 并解压，或使用 `git clone`。
2. 启动项目：
   - Windows：双击 `启动辩论场.bat`。
   - macOS / Linux：在项目目录运行 `chmod +x start.sh && ./start.sh`。
3. 浏览器会自动打开 `http://127.0.0.1:4173/`。首次使用时，在网页弹窗中粘贴 Kimi、DeepSeek 或两者的 API Key；点击输入框右侧的“显示”可以检查已输入的内容。
4. 为立场生成、正方、反方和交锋图总结 Agent 分别选择模型，输入自然语言辩题并生成双方观点。检查或修改观点后，点击“确认并开始立论”；以后也可以点击页面右上角的“API 密钥”重新配置。

密钥只会保存到本机的 `.env` 文件中；该文件已被 `.gitignore` 排除，不会上传到 GitHub。只需配置本场四个角色实际使用的模型服务。

- [申请 Kimi API Key](https://platform.moonshot.cn/console/api-keys)
- [申请 DeepSeek API Key](https://platform.deepseek.com/api_keys)

> API 调用可能产生费用，请在对应平台查看余额和计费规则。停止终端中的程序或点击页面上的“停止辩论”可停止继续调用。

> Kimi K3 始终使用思考模式，项目会采用较低推理强度以控制单轮等待时间。Kimi 开放平台可能要求充值后才能调用 K3，具体以 [Kimi K3 官方说明](https://platform.kimi.com/docs/guide/kimi-k3-quickstart) 为准。

## 手动配置

如果不使用网页配置，将 `.env.example` 复制为 `.env`，填写一个或两个密钥：

```dotenv
MOONSHOT_API_KEY=你的_Kimi_API_Key
DEEPSEEK_API_KEY=你的_DeepSeek_API_Key
```

然后运行：

```bash
python launcher.py --open
```

网页配置是推荐方式。也可以使用旧的终端配置向导：

```bash
python launcher.py --configure --open
```

`.env` 中还可以覆盖默认模型、接口及每次发言的限制：

```dotenv
KIMI_API_URL=https://api.moonshot.cn/v1/chat/completions
KIMI_MODEL=kimi-k2.6
DEEPSEEK_API_URL=https://api.deepseek.com/chat/completions
DEEPSEEK_MODEL=deepseek-v4-pro
AI_DEBATE_MAX_CHARS=600
AI_DEBATE_MAX_TOKENS=1600
AI_DEBATE_VIEWPOINT_MAX_TOKENS=400
AI_DEBATE_SUMMARY_MAX_TOKENS=2400
AI_DEBATE_REQUEST_TIMEOUT=90
AI_DEBATE_TURN_PAUSE=1
```

## 辩论流程

启动流程：

1. 立场生成 Agent 将自然语言输入压缩为正方观点与反方观点，双方合计不超过 50 字。
2. 用户检查、修改并二次确认；未经确认不会创建辩论或调用辩手。
3. 观点同时发送给双方。正方先生成立论，反方随后仅根据同一份确认观点生成立论。
4. 总结 Agent 整理立论阶段的交锋图，然后进入自由交锋。
5. 自由交锋中按“正方发言 → 反方发言 → 总结 Agent”循环，直到用户停止。

点击“暂停辩论”后，当前正在工作的 Agent 会先完成并保存本次输出，系统随后停在调用下一位 Agent API 之前。点击“继续辩论”即可按原顺序继续。

完成至少一轮总结后，可以点击控制栏中的“查看交锋图”。系统会在独立标签页打开当时已保存的数据快照，原辩论页保持运行。交锋图不会自动刷新；需要查看新一轮结果时，再次点击同一按钮即可让图页重新读取最新记录。

立论阶段不读取任何此前发言，双方只接收用户确认的正反观点；反方立论也不会读取正方刚生成的立论。进入自由交锋后，选手才会读取公开发言记录。项目没有私有策略记忆或其他预设攻辩阶段。总结 Agent 的结果单独保存在 `argumentGraph` 和 `roundSummaries`，不会写入 `speeches`，所以正反双方不会读取交锋图分析。

体系 Agent 只维护一张交锋图。第一轮为正反双方各建立一个“观点”根节点和 2–4 个不可修改的“核心论点”主分支；后续仅能增加“支持论据”或“反驳论据”。支持论据只能连接本方观点或核心论点，反驳论据可连接对方任意节点。正反双方共享 4 个支持论据资源和 10 个反驳论据资源，两类额度互不借用；核心论点与观点根节点不可新增、修改或删除。本方结构始终是树状，只有反驳论据可以跨越双方树结构。若一轮对话无法作用于既有观点或核心论点，体系 Agent 会拒绝入图、保存原因且不消耗论据资源。

总结 Agent 只接受可在本轮发言原文中逐字验证的节点来源，并使用 `supports` 与 `rebuts` 两种关系。它不判断胜负、不给论点评分，也不补充外部事实；无法验证或关系不明确的内容会被省略。

## 数据与隐私

- 服务只监听本机地址 `127.0.0.1`，不会主动把网页开放到局域网或公网。
- API Key 只由本地 Python 服务读取，不会发送给网页前端或写入辩论记录。
- 自然语言输入会先发送给立场生成 Agent。经确认的观点、辩论内容和已有交锋图会按角色发送给所选的 Kimi / DeepSeek API，并保存在 `data/debates/`。启动时包含一次观点生成调用；立论与每个自由交锋轮次各包含正方、反方、总结 Agent 三次调用。
- `data/debates/` 下的个人辩论记录也已被 Git 排除，只保留空目录占位文件。

每场辩论都会创建独立的“辩题名称 + 唯一记录 ID”文件夹：

```text
data/debates/
└── 人工智能的发展对人类社会利大于弊__debate_20260823T012000Z_78902813/
    └── debate.json
```

即使多次使用相同辩题，也不会覆盖此前记录。

## 项目结构

- `launcher.py`：启动本地服务；可选提供终端密钥配置向导。
- `debate_agent.py`：模型请求、固定身份辩手、客观总结 Agent 和轮次循环。
- `server.py`：本地 HTTP API、后台任务和 JSON 持久化。
- `index.html`、`styles.css`、`app.js`：辩论主界面。
- `graph.html`、`graph.css`、`graph.js`：手动读取数据的可视化交锋图界面。
- `tests/`：无需真实 API Key 的自动化测试。

运行测试：

```bash
python -m unittest discover -s tests -v
```

## 常见问题

- 提示找不到 Python：从 [Python 官网](https://www.python.org/downloads/) 安装 Python 3.10+，Windows 安装时勾选“Add Python to PATH”。
- 提示密钥未配置：点击页面右上角的“API 密钥”进行配置，或检查 `.env` 中对应的密钥。
- 浏览器没有自动打开：手动访问 `http://127.0.0.1:4173/`。
- 端口 4173 被占用：先关闭此前启动的 AI 辩论场或其他占用该端口的程序。
