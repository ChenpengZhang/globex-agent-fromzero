# 跨境Agent第四章

## 本章目标

本章把第三章已经测试通过的 `CatalogSearchUseCase` 包装成 AgentScope 工具，并将它注册到 MainAgent，第一次形成完整的 ReAct 工具调用循环。

```text
用户问题
    ↓
MainAgent / ChatModel
    ↓ ToolCallBlock
product_search_tool
    ↓
CatalogSearchUseCase
    ↓ ToolResultBlock
ChatModel 第二次调用
    ↓
最终自然语言回答
```

## 工具适配器

`build_product_search_tool()` 是工具工厂。外层函数接收系统依赖：

```python
build_product_search_tool(catalog_search_usecase)
```

内层函数只暴露模型需要填写的业务参数：

```text
normalized_query
category
ship_to
top_k
price_max_major
target_currency
```

因此模型不会看到 Repository 或 UseCase 等系统内部对象。

工具本身不复制搜索逻辑，只负责：

1. 把模型参数转换为 `ProductSearchSpec`。
2. 调用 `CatalogSearchUseCase`。
3. 把结果序列化为 JSON `ToolChunk`。
4. 把输入错误转换为 ERROR `ToolChunk`。

## FunctionTool 与 Schema

普通 Python 函数经过 `FunctionTool` 包装后，AgentScope 会读取：

```text
函数名       → 工具名
docstring    → 工具描述
类型注解     → JSON Schema 参数类型
默认值       → 参数是否必填
Args         → 参数说明
```

`normalized_query` 没有默认值，因此是唯一必填参数。其余参数具有默认值，在模型生成的工具调用中可以省略。

工具被标记为 `is_read_only=True`，表明商品搜索不会修改业务状态。以后订单创建和取消工具不能使用这个标记。

## MainAgent 与依赖注入

MainAgent 现在通过参数接收工具：

```python
create_main_agent(
    model=model,
    tools=[product_search_tool],
)
```

它只依赖 `ChatModelBase` 和 `FunctionTool`，不认识 `InMemoryProductRepository` 或 `CatalogSearchUseCase`。具体依赖全部由 Composition Root 组装。

模型类型从 `OpenAIChatModel` 收窄依赖改为 `ChatModelBase`，因此同一个 MainAgent 可以使用真实 OpenAI 兼容模型，也可以使用测试模型。

## Composition Root

本章的完整组装顺序是：

```text
seed products
    ↓
InMemoryProductRepository
    ↓
CatalogSearchUseCase
    ↓
Python tool function
    ↓
FunctionTool
    ↓
Toolkit
    ↓
MainAgent
```

CLI 没有因工具接入而修改，仍然只调用 `container.main_agent.reply()`。这说明 Presentation 不需要了解工具和业务依赖的构造细节。

## ReAct 循环

一次商品请求通常需要两次模型调用：

1. 第一次模型调用读取用户需求和工具 Schema，返回 `ToolCallBlock`。
2. AgentScope 根据工具名查找 FunctionTool，解析参数并执行 Python 函数。
3. 工具输出以 `ToolResultBlock` 加入上下文。
4. 第二次模型调用读取真实商品结果，生成最终文本。

`ReActConfig(max_iters=5)` 是循环上限，不代表每次一定调用模型五次。

## 无网络测试模型

`ScriptedChatModel` 是一个可复用的测试替身。它不会连接外部模型，而是依次返回预先定义的 `ChatResponse`，同时记录每次收到的 messages、tools 和 tool choice。

集成测试预设：

```text
第一次响应：调用 product_search_tool
第二次响应：根据工具结果给出最终回答
```

测试随后确认：

- Agent 第一次调用模型时提供了工具 Schema。
- 工具被真实执行，而不是测试直接伪造工具结果。
- 第二次模型调用中包含 `ToolResultBlock`。
- 工具结果包含 P1001、P1003 和预算过滤原因。
- Agent 返回第二次模型响应的最终文本。

## 测试覆盖与验收

本章测试总数为 17，全部通过：

- 前三章原有 13 项测试无回归。
- FunctionTool Schema 正确。
- 工具成功结果可以解析为 JSON。
- 非法输入返回 ERROR ToolChunk。
- 完整的模型调用、工具执行、模型复答循环通过无网络集成测试。

## 当前限制

- CLI 只处理一次用户输入。
- 没有独立 Orchestrator。
- 没有会话 ID、买家 ID、语言和币种上下文。
- 没有 HTTP API。
- 没有流式事件和工具调用可观测性。

## 下一章

下一章引入 `MainAgentOrchestrator` 和稳定的应用输入/输出 DTO，把 Presentation 从直接调用 Agent 改为调用应用用例：

```text
CLI → SubmitIntentInput → Orchestrator → MainAgent → SubmitIntentOutput
```
