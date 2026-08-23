# AI 辩论场

一个在本机运行的双 AI 自动辩论网页应用。正反双方可以自由选择 Kimi 或 DeepSeek，程序会让两名固定立场的 Agent 按轮次持续发言，直到用户暂停或停止辩论。

## 快速开始

运行要求：Python 3.10 或更高版本。项目只使用 Python 标准库，不需要执行 `pip install`。

1. 下载项目：点击 GitHub 页面上的 **Code → Download ZIP** 并解压，或使用 `git clone`。
2. 启动项目：
   - Windows：双击 `启动辩论场.bat`。
   - macOS / Linux：在项目目录运行 `chmod +x start.sh && ./start.sh`。
3. 浏览器会自动打开 `http://127.0.0.1:4173/`。首次使用时，在网页弹窗中粘贴 Kimi、DeepSeek 或两者的 API Key；点击输入框右侧的“显示”可以检查已输入的内容。
4. 保存后输入辩题即可开始；以后也可以点击页面右上角的“API 密钥”重新配置。

密钥只会保存到本机的 `.env` 文件中；该文件已被 `.gitignore` 排除，不会上传到 GitHub。只有本场实际选择的模型需要配置密钥。例如正反双方都选择 Kimi 时，只需配置 Kimi 密钥。

- [申请 Kimi API Key](https://platform.moonshot.cn/console/api-keys)
- [申请 DeepSeek API Key](https://platform.deepseek.com/api_keys)

> API 调用可能产生费用，请在对应平台查看余额和计费规则。停止终端中的程序或点击页面上的“停止辩论”可停止继续调用。

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
AI_DEBATE_REQUEST_TIMEOUT=90
AI_DEBATE_TURN_PAUSE=1
```

## 辩论流程

每轮的结构固定：

1. 正方读取辩题和此前公开发言，生成一次发言。
2. 反方读取辩题和包含正方新发言的公开记录，生成一次发言。
3. 轮数加一并重复，直到用户停止辩论。

点击“暂停辩论”后，正在发言的选手会先完成并保存本次发言，系统随后停在调用下一位选手 API 之前。点击“继续辩论”即可按原顺序继续。

选手只保留自己的固定身份。没有立论、反驳、攻辩或总结等预设阶段，也没有私有策略记忆。

## 数据与隐私

- 服务只监听本机地址 `127.0.0.1`，不会主动把网页开放到局域网或公网。
- API Key 只由本地 Python 服务读取，不会发送给网页前端或写入辩论记录。
- 辩论内容会发送给所选的 Kimi / DeepSeek API，并保存在 `data/debates/`。
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
- `debate_agent.py`：模型请求、固定身份辩手和轮次循环。
- `server.py`：本地 HTTP API、后台任务和 JSON 持久化。
- `index.html`、`styles.css`、`app.js`：网页界面。
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
