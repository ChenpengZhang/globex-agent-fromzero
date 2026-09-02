# 跨境 Agent 第六章：FastAPI HTTP 边界

## 本章目标

本章在 CLI 之外增加 HTTP Presentation Adapter，使外部客户端可以通过 JSON 提交购物意图，同时继续复用第五章的 Orchestrator。

```text
HTTP JSON
    ↓
SubmitIntentRequest（Pydantic）
    ↓
SubmitIntentInput（Application）
    ↓
MainAgentOrchestrator
    ↓
SubmitIntentOutput
    ↓
SubmitIntentResponse（Pydantic）
```

## HTTP DTO 与 Application DTO

`SubmitIntentRequest` 和 `SubmitIntentResponse` 属于 Presentation，负责 JSON 解析、HTTP 校验、OpenAPI Schema 和响应序列化。

`SubmitIntentInput` 和 `SubmitIntentOutput` 属于 Application，表达与传输协议无关的用例输入输出。CLI 与 HTTP 都转换成相同的 Application DTO，因此 Agent 调用逻辑没有复制。

字段相似不代表职责相同：

```text
Pydantic DTO       外部 HTTP 契约
Application DTO    内部应用契约
```

## FastAPI 应用工厂

`build_app(container=None)` 使用应用工厂而不是在模块导入时固定所有依赖。

正式运行时不传 Container，由 Composition Root 创建真实模型和业务依赖；测试时注入无网络 Container。这样 HTTP 测试不会调用外部模型，也不需要测试密钥。

## 接口

### GET /health

返回当前进程的基础健康状态：

```json
{"status": "ok"}
```

本章的健康检查只表示应用可响应，不代表模型、数据库等未来外部依赖都健康。

### POST /commerce/intents

接收 buyer、locale、currency、raw query 和可选 session ID。缺少 session ID 时，服务端生成 `session-` 加八位十六进制字符的标识。

路由只做协议转换：HTTP DTO → Application DTO → Orchestrator → HTTP Response。它不包含搜索、工具或 Agent 推理逻辑。

## Pydantic 校验

HTTP 边界会：

- 去除字符串两侧空白。
- 要求 buyer ID 和 raw query 非空。
- 将币种规范化为大写。
- 限制币种为三位代码。
- 对非法请求返回 HTTP 422。

Application DTO 仍保留自己的校验，因为 CLI、Worker 等非 HTTP 入口不会经过 Pydantic。

## 无网络 API 测试

FastAPI `TestClient` 使用注入的 `ScriptedChatModel`，覆盖：

- 健康接口。
- 自动生成 session ID。
- 保留调用方指定的 session ID。
- HTTP 默认 locale 与 currency 进入 Agent 消息。
- 小写币种被规范化。
- 缺少 buyer/query、空 query、非法币种返回 422。

本章新增 7 项测试，全套共 30 项，全部通过。

## 当前限制

- session ID 目前只是请求与响应字段。
- 所有请求仍共享 Container 中的唯一 MainAgent 和 AgentState。
- 不同 session 和 buyer 尚未实现上下文隔离。
- 没有认证、持久化、流式响应或 WebSocket。

因此当前 API 不能作为安全的多用户聊天服务。

## 下一章

下一章引入 `MainAgentFactory` 与 `SessionRegistry`：

```text
session-A → Agent A → AgentState A
session-B → Agent B → AgentState B
```

同时绑定 session 与 buyer，防止不同买家复用同一会话。
