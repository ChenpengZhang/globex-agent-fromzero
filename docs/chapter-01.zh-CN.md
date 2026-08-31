# 第一章：最小单 Agent 系统

## 本章目标

从空目录开始，构建一个能够接收命令行输入并调用大模型的最小 Agent 系统。

本章只关注以下调用链：

```text
命令行输入
    ↓
MainAgent
    ↓
ChatModel
    ↓
大模型服务
    ↓
最终回答
```

本章不包含商品工具、数据库、RAG、子 Agent、缓存、WebSocket 或前端。

## 项目结构

```text
app/
├── application/
│   └── agents/
│       └── main_agent.py
├── domain/
├── infrastructure/
│   ├── settings.py
│   └── llm.py
├── presentation/
│   └── cli.py
└── composition.py
```

## 各层职责

### Presentation

`app/presentation/cli.py` 接收命令行输入，将用户文本转换为 `UserMsg`，调用 MainAgent，并展示最终结果。

### Application

`app/application/agents/main_agent.py` 定义 Agent 的名称、系统提示词、模型和工具箱。

当前工具箱为空，因此 Agent 只能使用大模型自身的语言能力。

### Infrastructure

`app/infrastructure/settings.py` 从环境变量读取模型配置。

`app/infrastructure/llm.py` 使用配置创建 AgentScope 的 `OpenAIChatModel`。

### Domain

本章还没有商品、订单等业务规则，因此 Domain 层暂时为空。

### Composition Root

`app/composition.py` 负责组装配置、模型和 MainAgent。

它只负责依赖连接，不处理用户输入，也不包含业务规则。

## 核心概念

### 模型不等于 Agent

ChatModel 只负责向大模型服务发送消息并接收响应。

Agent 在模型外增加了：

- 身份与系统提示词
- 对话状态
- 工具箱
- 推理与工具调用循环

### 依赖注入

MainAgent 不负责创建模型，而是通过参数接收模型：

```python
def create_main_agent(model: OpenAIChatModel) -> Agent:
    ...
```

模型由 Composition Root 创建并注入 MainAgent。

这样可以在未来替换模型，而不修改 Agent 的主要业务定义。

### Presentation 与应用逻辑分离

当前用户通过命令行输入。未来切换为 HTTP、WebSocket 或前端时，只需要替换或增加 Presentation 层，不需要重写 MainAgent。

## 启动方式

在项目根目录执行：

```bash
uv run python -m app.presentation.cli
```

然后在命令行输入问题。

## 当前限制

- 只支持单次命令行输入。
- 没有业务工具。
- 没有商品数据。
- 没有多轮会话管理。
- 没有流式输出。
- Agent 不得编造商品、价格、库存或订单信息。

## 下一章

下一章将建立商品领域模型，包括：

- Money 值对象
- SKU 实体
- Product 聚合根
- ProductRepository 端口

这些业务对象不会依赖 AgentScope 或具体数据库。