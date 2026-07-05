# DataNex-Invest（数境智投）

基于 **新闻情感分析 + 大模型 RAG** 的 A 股投研辅助工作台。整合实时行情、公告资讯、情感预测、自选盯盘与 AI 投资助手，为个人投资者提供查询、分析与参考决策支持。

> **重要提示**：本系统所有预测与 AI 回答仅供学习研究参考，**不构成任何投资建议**。股市有风险，投资需谨慎。

---

## 功能特性

| 模块 | 说明 |
|------|------|
| **工作台** | 热股快照、自选盯盘、快捷入口 |
| **股票搜索** | 代码/名称/拼音检索，支持别名 |
| **自选股** | 添加/删除自选，批量实时报价，本地缓存加速 |
| **公告情感分析** | 拉取个股公告，TF-IDF + FinBERT + 规则融合 |
| **情感预测** | 基于公告情感预测未来 3 个交易日涨跌方向，含置信度与依据链接 |
| **热点新闻** | 东方财富热点抓取，过期缓存 + 后台刷新 |
| **新闻词云** | jieba 分词 + 停用词过滤，生成词频词云 |
| **K 线 / 回报率** | akshare 行情，ECharts / mplfinance 可视化 |
| **AI 投资助手** | RAG 知识库（44+ 条）+ 实时行情/基本面 + SiliconFlow 大模型，支持流式输出 |
| **用户系统** | 注册登录、个人资料、新手引导 |

---

## 系统架构

```
浏览器 (HTML + JS)
       ↓
Flask 应用 (app.py)
       ├── SQLite          用户 / 自选股
       ├── akshare / 东财   行情、公告、基本面
       ├── FinBERT + RF     情感预测 (models/)
       ├── RAG 知识库       knowledge/stock_knowledge.json
       └── SiliconFlow API  AI 助手 (DeepSeek-V3)
```

**AI 助手链路**：用户提问 → 并行检索知识库 + 拉取行情 → 大模型流式生成 → 术语纠错 / 截断续写 → 返回答案与参考来源。

---

## 环境要求

- **Python** 3.10+（推荐 3.10 / 3.11）
- **操作系统**：Windows / Linux / macOS
- **网络**：需访问 akshare 数据源、东方财富、SiliconFlow API
- **可选**：NVIDIA GPU（加速 FinBERT，CPU 亦可运行）

---

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/heranxin/DataNex-Invest.git
cd DataNex-Invest
```

### 2. 创建虚拟环境（推荐）

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

> 首次安装 `torch`、`transformers` 体积较大，请耐心等待。若仅需 Web 与 AI 助手、暂不跑情感预测，可先跳过 GPU 版 PyTorch，使用 CPU 版。

### 4. 配置环境变量

```bash
# Windows
copy .env.example .env

# Linux / macOS
cp .env.example .env
```

编辑 `.env`，填入 AI API 密钥（见下方 [AI 助手配置](#ai-助手配置)）。

### 5. 启动服务

```bash
python app.py
```

浏览器访问：**http://127.0.0.1:5000**

首次运行会自动创建 `instance/users.db` 数据库。注册账号后即可使用。

---

## 配置说明

### `.env` 文件

| 变量 | 必填 | 说明 |
|------|------|------|
| `SILICONFLOW_API_KEY` | AI 助手必填 | [硅基流动](https://cloud.siliconflow.cn/) API 密钥 |
| `AI_MODEL` | 否 | 默认 `deepseek-ai/DeepSeek-V3` |
| `AI_API_BASE` | 否 | 默认 `https://api.siliconflow.cn/v1/chat/completions` |
| `AI_MAX_TOKENS` | 否 | 生成长度上限，默认 `1800` |

未配置 `SILICONFLOW_API_KEY` 时，AI 助手仍可运行，但仅使用知识库检索模式，不会调用大模型。

### 代理环境

若本机开启系统代理导致 akshare / 东方财富请求失败，项目内 `model/network_utils.py` 提供了 `direct_connection()` 上下文管理器，在部分模块中会自动绕过代理直连。

---

## 主要功能使用

### 注册与登录

1. 访问首页 → 注册账号  
2. 登录后进入 **工作台（Dashboard）**

### 自选股盯盘

1. 侧栏或工作台搜索股票代码（如 `600519`）  
2. 进入个股页或自选页 → **添加自选**  
3. 工作台 / 自选页可查看批量报价，支持后台静默刷新

### 公告情感与预测

1. 进入 **情感分析** 或 **股票预测** 页面  
2. 输入 6 位 A 股代码（如 `600519`）  
3. 系统拉取近期公告 → 情感分析 → 输出涨跌趋势、置信度、新闻链接

### 热点新闻与词云

- **热点新闻**：工作台或「热点资讯」入口  
- **词云**：输入股票代码，基于近期资讯生成词云图

### AI 投资助手

- **抽屉模式**：任意页面右下角「AI 投资助手」悬浮按钮  
- **全屏模式**：侧栏「AI 股票助手」  
- 支持流式逐字输出、对话历史（浏览器 localStorage 共享）  
- 问法示例：
  - `什么是市盈率 PE？`
  - `分析一下 600519`
  - `怎么筛选指数基金和主动股基？`

---

## AI 助手配置

1. 注册 [硅基流动 SiliconFlow](https://cloud.siliconflow.cn/)  
2. 控制台 → **API 密钥** → 创建密钥  
3. 写入 `.env`：

```env
SILICONFLOW_API_KEY=sk-你的密钥
AI_MODEL=deepseek-ai/DeepSeek-V3
AI_MAX_TOKENS=1800
```

4. 重启 `python app.py`  
5. 提问后若标签显示 **DeepSeek-V3**，表示大模型已接通

**模型建议**：

| 场景 | 模型 |
|------|------|
| 质量优先 | `deepseek-ai/DeepSeek-V3` |
| 速度优先 | `deepseek-ai/DeepSeek-V4-Flash` |

---

## 模型训练（可选）

仓库已包含预训练模型（`models/` 目录，约 34MB）。如需重新训练：

```bash
# 1. 构建/更新训练数据集
python model/build_dataset.py

# 2. 训练情感 + 价格预测模型
python model/train.py
```

**FinBERT 说明**：

- 优先加载项目根目录 `finbert/` 本地模型  
- 若本地不存在，会尝试从 HuggingFace 下载 `ProsusAI/finbert`  
- 可将 FinBERT 模型文件放入 `finbert/` 以避免重复下载

训练数据：`model/data/stock_news_real.csv`（真实 A 股公告-收益样本）

---

## 项目结构

```
DataNex-Invest/
├── app.py                  # Flask 主入口、路由、用户系统
├── news.py                 # 热点/公告抓取
├── utils.py                # 公告列表工具
├── stock_data.py           # 行情封装
├── test.py                 # K 线图表
├── requirements.txt
├── .env.example            # 环境变量模板（复制为 .env）
├── knowledge/
│   └── stock_knowledge.json   # AI RAG 知识库
├── model/
│   ├── ai_assistant.py     # AI 助手（RAG + LLM）
│   ├── predict.py          # 预测推理
│   ├── train.py            # 模型训练
│   ├── news_analysis.py    # 情感规则、行业、基本面
│   ├── favorite_quotes.py  # 自选行情
│   ├── stock_search.py     # 搜索索引
│   └── wordcloud_utils.py  # 词云预处理
├── models/                 # 已训练 ML 模型
├── templates/              # 页面模板
├── static/                 # CSS / JS / 图片
├── scripts/                # 部署与运维脚本
└── tests/                  # 测试
```

---

## 部署说明（生产环境）

开发环境直接使用 `python app.py` 即可。生产环境建议：

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

配合 **Nginx** 反向代理。可参考 `scripts/server_setup_env.sh` 与 `scripts/remote_setup.py`。

**切勿**将 `.env`、`instance/users.db` 提交到 Git（已在 `.gitignore` 中忽略）。

---

## 常见问题

### 1. 行情 / 新闻拉取失败？

- 检查网络，关闭或配置系统代理  
- akshare 接口偶发限流，稍后重试  
- 热点新闻会使用过期缓存兜底

### 2. AI 助手只有「检索模式」？

- 检查 `.env` 中 `SILICONFLOW_API_KEY` 是否填写  
- 检查 SiliconFlow 账户余额  
- 修改 `.env` 后需重启 Flask

### 3. AI 回答乱码？

- 浏览器 **Ctrl+F5** 强刷  
- 确认 `static/js/ai-chat-client.js` 为最新版本

### 4. 情感预测报错 FinBERT？

- 确保已安装 `torch`、`transformers`  
- 首次运行需下载模型，或手动放入 `finbert/` 目录

### 5. 数据库在哪里？

- 默认：`instance/users.db`（SQLite，首次运行自动创建）

---

## 主要 API 一览

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/stock-search` | GET | 股票搜索 |
| `/api/favorite-quotes` | GET | 自选批量报价 |
| `/api/stock-news` | GET | 个股公告列表 |
| `/api/stock-prediction` | GET | 情感预测 |
| `/api/hot-news` | GET | 市场热点 |
| `/api/ai-chat` | POST | AI 对话（支持 `stream: true`） |

---

## 免责声明

1. 本系统为 **投研学习与辅助工具**，不提供证券投资咨询业务。  
2. 预测模型、AI 生成内容可能存在误差，**不构成买卖建议**。  
3. 行情与基本面数据来自公开接口，不保证实时性与完整性。  
4. 用户应独立判断并自行承担投资风险。

---

## 开源与贡献

- 仓库：https://github.com/heranxin/DataNex-Invest  
- 欢迎提交 Issue 与 Pull Request  
- 知识库条目可在 `knowledge/stock_knowledge.json` 中扩展，修改后重启服务即可自动重建 RAG 索引

---

## 技术栈

Flask · SQLAlchemy · SQLite · akshare · scikit-learn · FinBERT · jieba · ECharts · SiliconFlow (DeepSeek-V3)
