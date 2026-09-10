# 第十六章：文件持久化与恢复

## 本章目标

本章先不引入关系型数据库，而是让一次购物对话在后端进程重启后仍然可以恢复。
系统增加了两种刻意分开的持久化数据：

```text
AgentState 快照    恢复 Agent 内部继续推理所需的对话上下文
Conversation 流水  恢复用户和前端能够阅读的对话及执行记录
```

这一区分非常重要。Agent state 是框架相关的运行数据，目的是让 Agent 接着思考；
conversation history 是面向应用的记录，目的是供 API 和前端读取。我们没有强迫同
一种数据结构同时承担两个职责。

文件 Adapter 是学习过程中的过渡实现。第 17 章替换为数据库 Adapter 时，端口和
Application 流程可以保持稳定。

## DDD 边界

本章继续让持久化细节依赖向内的契约：

```text
Domain
├── SessionStore
├── ConversationStore
├── ConversationTurn
└── ConversationEventRecord

Application
├── SessionRegistry
├── MainAgentOrchestrator
└── GetConversationHistoryUseCase

Infrastructure
├── JsonFileSessionStore
├── JsonFileConversationStore
└── safe_storage_name

Presentation
├── GET /commerce/sessions/{session_id}/history
└── React 历史加载
```

Domain 只定义系统需要保存和读取什么，不知道路径、JSONL、FastAPI 或 React。
Infrastructure 实现这些端口；Application 决定何时持久化，并编排历史查询；
Presentation 只负责传输数据的转换。

`SessionStore` 和 `ConversationStore` 被拆成两个端口，是因为它们的数据形态和写入
模式不同：session 快照会覆盖旧值，而对话轮次和事件是一条只追加的流水。

## Agent 状态恢复

`SessionRegistry` 仍然负责管理进程内的 Agent 实例和每个 session 的执行锁。当前
进程第一次收到某个 session 时，会经过下面的路径：

```text
get_or_create(session_id, buyer_id)
    ├── 内存中已有 entry → 检查 buyer → 复用 Agent
    └── 内存中没有 entry
          └── SessionStore.load(session_id)
                ├── 没有快照 → 创建新 Agent
                ├── 快照有效 → 恢复 AgentState → 创建 Agent
                ├── 属于其他 buyer → 拒绝访问
                └── 快照损坏 → 记录 warning → 创建新 Agent
```

`MainAgentFactory.build(state=...)` 把恢复出的 `AgentState` 注入框架 Agent。Agent 的
模型、工具、prompt 和配置仍然由 Factory 管理，Registry 不需要知道这些构造细节。

每次 Agent 执行结束后，Orchestrator 都会在 `finally` 中调用
`SessionRegistry.persist()`，因此成功和失败的执行都会尝试保存状态。文件中的外壳
同时保存 owner 和框架 state：

```json
{
  "buyer_id": "buyer-001",
  "state_json": "{...serialized AgentState...}"
}
```

把 buyer ID 与 state 一起保存，可以在进程重启后继续执行 session 所有权检查。
仅仅猜中一个 session ID，不足以读取另一个 buyer 的 Agent 上下文。

快照保存失败只会记录日志，不会把原本的业务响应替换成持久化错误。这是当前学习
阶段采用的 best-effort 策略。

## 可读对话流水

每个 session 的 JSONL 文件中保存三种记录：

```text
session   buyer 所有权、locale、currency、创建与更新时间
turn      buyer 或 Agent 文本、model、latency 和时间
event     事件类型、结构化 payload 和发生时间
```

JSONL 每行写入一个 JSON 对象。追加新 turn 或 event 时，不需要解析并重写全部历史。
重复出现的 `session` 记录相当于 metadata 更新；`find_session()` 读取最后一条，同时
保留最初的创建时间。

buyer turn 保存的是 `raw_query`，而不是内部加入 `<shopping-context>` 后的消息。这
能让用户看到的历史保持整洁，也不会把传输和运行期 metadata 暴露到聊天记录中。

只有获得最终回答时才写入 Agent turn。如果 Agent 执行失败，仍可保留 buyer 尝试
发送的内容和非 token 错误事件，但系统不会虚构一条空的 Agent 回复。

## 事件采集

Orchestrator 会为当前执行的 session 临时订阅已有 EventBus：

```text
获取 session lock
    → 订阅临时 trace queue
    → 运行 Agent 并发布事件
    → 取消订阅
    → 把 queue 转换成 ConversationEventRecord
    → 追加到流水
```

订阅发生在获得 session 执行锁之后，这样同一 session 中排队的两个请求不会采集到
彼此的 trace。

`token.delta` 被有意排除在持久化之外。几百个 token 碎片会增加体积，却不能改善
历史恢复，因为最终 Agent turn 已经保存了完整文本。`final.result`、`error` 以及
未来的 Tool/子 Agent 高层事件则保留结构化记录。

目前 event 仅作为可观测流水保存。历史接口只返回可读 turns，WebSocket 也仍然只
传递实时事件；本章没有实现事件回放。

## 安全文件名

外部输入的 session ID 不会直接成为文件路径。`safe_storage_name()` 使用受限的可读
前缀，再拼接一段完整原值的 SHA-256 摘要：

```text
外部原始 ID
    → 只保留字母、数字、连字符和下划线作为短前缀
    → 拼接基于完整原值计算的 hash
```

受限前缀可以防止路径穿越，摘要则让清洗后相同的值仍然保持不同，例如 `a/b` 和
`ab` 不会映射成同一个文件。

运行数据位于配置的数据目录下：

```text
data/
├── sessions/
│   └── <safe-session-name>.json
└── conversations/
    └── <safe-session-name>.jsonl
```

## 历史查询 UseCase 与 HTTP API

`GetConversationHistoryUseCase` 是历史查询的 Application 边界。它负责：

1. 校验并规范化 `session_id`、`buyer_id` 和 `limit`；
2. 确认 conversation metadata 存在；
3. 读取 turns 之前检查 buyer 所有权；
4. 请求 Store 返回指定数量的最新 turns，并保持原始顺序；
5. 把 Domain record 映射为输出 DTO。

Presentation 层暴露下面的接口：

```http
GET /commerce/sessions/{session_id}/history?buyer_id=buyer-001&limit=50
```

响应包含 `session_id` 和可读的 buyer/Agent turns。当前状态码语义如下：

```text
200   返回历史
403   session 属于其他 buyer
404   conversation session 不存在
422   path/query 参数校验失败
```

所有权检查提供了必要的隔离，但当前 `buyer_id` 仍是客户端提供的学习阶段标识，不是
经过认证的用户身份。

## 前端恢复

React 启动或 `shopping_session_id` 改变时，会先请求历史，再允许发送新消息：

```text
读取浏览器中的 buyer/session ID
    → 请求历史
        ├── 200 → 校验响应 → 渲染已保存 turns
        ├── 404 → 当作全新的空对话
        └── 其他错误 → 显示错误提示
```

Effect 使用 cancellation guard，防止旧 session 的慢响应覆盖刚刚切换的新对话。
网络数据进入 View state 前还会经过运行时校验。页面只恢复聊天 turns，不恢复历史
token 碎片，也不回放旧的 event timeline。

## 完整运行链路

现在，一次成功对话会经过下面的完整管线：

```text
React
  → POST /commerce/intents
  → FastAPI request DTO
  → SubmitIntentInput
  → MainAgentOrchestrator
      → SessionRegistry.get_or_create
          → 必要时读取 AgentState 快照
      → 获取当前 session lock
      → 订阅 event trace
      → Agent.reply_stream
      → 发布 token.delta 和 final.result
      → finally:
          → 保存 AgentState 快照
          → 保存可读 buyer/Agent turns
          → 保存非 token 执行事件
          → reset ShoppingContext
  → 返回最终 HTTP 响应

后续刷新页面
  → GET history
  → GetConversationHistoryUseCase
  → ConversationStore
  → React 渲染恢复出的 turns
```

## 失败策略

本章尽量保证可选的记录能力不会让 Agent 主流程失效：

- 无法读取或格式损坏的 Agent 快照会降级为新 Agent；
- 属于其他 buyer 的快照不会被忽略，而是明确拒绝；
- state 保存失败只记录日志；
- conversation 保存失败只记录日志；
- 损坏的 JSONL 行会被跳过，其他合法记录仍可读取；
- Agent 执行异常会在尝试持久化后继续向上抛出。

这种策略偏向服务连续性，但 Agent 快照、对话流水和业务 Repository 之间没有事务
一致性保证。

## 验证结果

完成后的实际检查结果：

```text
后端全量回归测试：                  248 passed
前端 TypeScript + Vite 生产构建：   通过
```

测试覆盖了跨 Registry 实例恢复 state、重启后的 buyer 所有权、失败时保存、文件名
安全、metadata 刷新、历史顺序与 limit、损坏行容错、event batch、UseCase 映射、
HTTP 状态码，以及从 Orchestrator 写入到历史查询的完整链路。

## 当前限制

- 端口虽然是 async，但文件 I/O 仍然是同步操作。
- 覆盖快照不是原子文件事务。
- JSONL 追加没有跨进程锁。
- 两个文件不能作为同一个事务提交，崩溃后可能短暂不一致。
- 快照损坏时会创建新 Agent，不会根据可读 turns 重建 AgentState。
- conversation events 已保存，但还不能查询或回放。
- 尚无保留期限、压缩、迁移、索引和备份策略。
- 订单与库存 Repository 仍在内存中，进程重启后会丢失。
- buyer ID 只能用于隔离检查，不能作为身份认证凭据。

这些限制是有意保留的。第 17 章会在相同端口后面加入关系型数据库持久化，分别学习
schema、事务、约束和数据库 Adapter，而不会把这些概念混进第一次恢复实现。长期
买家记忆顺延到第 18 章。
