# 第 18 章：买家长期记忆

## 本章目标

第 18 章为电商 Agent 加入持久化、按 buyer 隔离的长期偏好。买家可以明确要求 Agent 记住一个稳定偏好，在后续购物 session 中继续使用，并在将来撤回它。

它与对话历史并不是一回事：

- 对话历史属于某个 shopping session；
- 长期偏好属于 buyer；
- 进程重启不应清空这两类信息；
- 一次性购买要求必须留在当前对话中，不能自动升级为长期记忆。

本章沿用参考项目的双路径设计：

```text
写路径：模型 → remember/forget 工具 → PreferenceStore → 数据库
读路径：Orchestrator → PreferenceStore → PreferenceSelector → Agent hint
```

模型负责判断用户的明确表达是否需要调用记忆工具。确定性代码负责 buyer 身份、校验、持久化、隔离、删除、数量限制和失败处理。

## 实现范围

本章实现了：

- `BuyerPreference` 领域对象；
- `PreferenceStore` 领域端口；
- SQLAlchemy 表和 SQLite Adapter；
- 记住与撤回两个 FunctionTool；
- 通过 `ShoppingContext` 获取可信的请求级 buyer 身份；
- 支持可选 embedding 相关性排序的偏好筛选；
- 向 MainAgent 和 SearchAgent 注入 hint；
- 环境配置和 composition root 装配；
- 单元、集成、隔离、降级和跨 session 测试。

本章暂不引入：

- Redis 缓存；
- 异步偏好抽取；
- 从每段对话中自动推断偏好；
- 偏好编辑或语义合并；
- 过期策略和后台管理；
- 分布式缓存失效通知。

## DDD 边界

### Domain

Domain 保存业务含义和持久化契约：

```text
app/domain/buyer/preference.py
app/domain/buyer/ports/preference_store.py
```

`BuyerPreference` 包含：

- `buyer_id`：长期所有者；
- `kind`：`like` 或 `dislike`；
- `statement`：可以独立理解的偏好描述；
- `created_at`：不可变的创建时间。

领域对象会清理身份与描述两端的空白，并拒绝空身份、空描述和不支持的种类。

`PreferenceStore` 只暴露持久化操作：

```python
append(preference)
list_by_buyer(buyer_id)
delete(buyer_id, statement)
```

相关性检索没有放进该端口。如果把向量排序放到 `PreferenceStore`，所有持久化 Adapter 都会被迫依赖 embedding。相关性属于应用策略，不是持久化职责。

### Application

Application 层包含：

- 把 Agent 调用转换为领域操作的记忆工具；
- 为当前请求挑选有效子集的 `PreferenceSelector`；
- Orchestrator 输入增强；
- SearchAgent 派发输入增强；
- 约束工具调用时机的静态提示词规则。

### Infrastructure

Infrastructure 层包含：

- `buyer_preferences` SQL 表；
- `SqlPreferenceStore`；
- 相关性排序复用的现有 embedding client；
- 环境配置。

### Composition root

`app/composition.py` 创建一个偏好 Store 和一个 Selector，并把同一实例交给工具、任务派发和 Orchestrator。这里保持显式接线。Composition root 本来就可以同时认识领域端口和具体基础设施 Adapter。

## 持久化模型

SQL 表保存：

```text
id
buyer_id
kind
statement
created_at
```

数据库规则包括：

- `kind` 只能是 `like` 或 `dislike`；
- `(buyer_id, kind, statement)` 必须唯一；
- 重复 append 具有幂等性；
- 查询按照插入 ID 排序；
- 删除必须同时匹配 buyer 和 statement 原文。

三元唯一约束允许两个买家拥有相同偏好，同时防止某个买家的同种偏好因为重复工具调用而产生重复行。

## 为什么进入 SQLite，而不是 Redis

长期记忆属于 source of truth 数据。Redis 很适合加速读取和跨进程协调，但缓存不应该成为买家偏好的唯一长期所有者。

因此，本章通过 `PreferenceStore` 把偏好写入 SQLite。第 19 章可以在 Store 前增加 Redis，但关系型数据库仍然是权威来源：

```text
请求 → 可选 Redis 缓存 → PreferenceStore → 关系型数据库
```

即使 Redis 被清空或临时不可用，仍然可以从数据库重建买家记忆。

## 写路径：记住偏好

提示词只允许在买家明确表达稳定、预计跨多次购买持续有效的偏好时调用 `remember_preference_tool`。

适合长期记忆的例子：

- “我不买塑料材质。”
- “我通常喜欢极简设计。”
- “我一般会选择轻量化旅行用品。”

应该只留在当前对话的例子：

- “这次我想要红色。”
- “我今天预算 300 元。”
- “这个订单寄到上海。”

工具只接受：

```text
kind
statement
```

它不接受 `buyer_id` 或 `shopping_session_id`。这两个值来自可信的 `ShoppingContext`，避免模型把偏好写到其他买家名下。

工具发布 `tool.invoke` 和 `tool.result` 事件，创建并校验领域对象，通过端口落库，并且只在持久化成功后返回成功结果。

## 删除路径：撤回偏好

只有买家明确撤回一个长期偏好时，MainAgent 才应调用 `forget_preference_tool`。

删除条件被有意设计成精确匹配：

```text
buyer_id + statement 原文
```

模糊删除很危险，因为两个相似句子可能具有不同含义。提示词要求模型从注入的偏好块中复制 statement 原文。

如果没有找到完全匹配的记录，工具不会猜测。它返回成功状态，但明确说明没有删除任何内容，并列出剩余 statement，方便模型使用原文或向用户确认。

## 读路径与偏好筛选

MainAgent 处理请求前，Orchestrator 使用当前 `buyer_id` 查询偏好，并调用：

```python
PreferenceSelector.select(
    preferences=preferences,
    query=current_query,
    top_k=configured_top_k,
)
```

Selector 对两种偏好采用不同规则：

- 所有 `dislike` 都保留，因为它代表限制或黑名单；
- `top_k` 只限制 `like`；
- like 数量没有超过 `top_k` 时，不调用 embedding；
- 关闭相关性排序时，选择创建时间较新的 like；
- 开启相关性排序时，根据当前 query 的余弦相似度排列 like；
- embedding 异常、结果数量不匹配或向量维度不一致时，回退到时间排序。

该规则既保留安全限制，又限制了注入上下文的软个性化信息量。

## Embedding 何时调用

Selector 复用已有的 `EmbeddingClient` 抽象。因此 embedding 可以来自配置的线上 OpenAI-compatible API，但默认并不强制使用。

默认配置：

```dotenv
PREFERENCE_RELEVANCE_ENABLED=0
PREFERENCE_TOP_K=5
PREFERENCE_SUBAGENT_INJECT=1
```

关闭相关性排序时，偏好选择不会产生额外 embedding API 调用。开启后，只有 like 数量超过 `top_k` 时，Selector 才会批量计算候选 statement 的 embedding，并额外计算一次当前 query 的 embedding。

这个过程不需要微调模型。它是查询时的相似度检索，不是模型训练。

## Hint 注入与 Prompt Cache

筛选后的偏好被渲染为独立的内部 user 风格消息：

```text
<buyer-preferences>
- [dislike] 不要塑料材质
- [like] 喜欢极简设计
</buyer-preferences>
```

它们不会被动态拼进静态 system prompt。这样可以让较长的 system prefix 保持稳定，更有利于供应商侧的 Prompt Cache；只有较短的 buyer 专属 hint 是动态内容。

可读对话存储只保存买家的原始问题和 Agent 最终回复，不会把内部 memory hint 伪装成买家消息写入历史。

在同一个活跃 session 中，如果渲染后的偏好没有变化，不会重复注入。AgentState 中已经保留了之前的 hint。

## MainAgent 与子 Agent 策略

MainAgent 会收到相关偏好，因为它需要决定如何回答、搜索、推荐和派发任务。

复杂检索被派发时，SearchAgent 也会收到同一类偏好 hint。SearchAgent 看不到 MainAgent 的对话历史，因此服务端注入可以避免让父 Agent 把隐藏记忆复制进 `demands`。

TradeAgent 不接收偏好。交易专家只应该执行已经确认的 product ID、SKU、数量、地址和订单命令，不能让软推荐偏好重新解释一笔已确认交易。

## 失败策略

长期个性化有价值，但普通购物请求不应依赖它才能完成。因此：

- 偏好读取失败时记录日志，并让 Agent 在没有 hint 的情况下继续；
- 相关性计算失败时回退到时间排序；
- SearchAgent 偏好注入失败时仍然继续派发；
- 写入和删除失败时返回明确工具错误，模型不得声称操作成功。

也就是：可选的读取增强采用 fail-open，记忆修改采用 fail-closed。

## 请求链路

记住：

```text
买家表达稳定偏好
→ MainAgent 选择 remember_preference_tool
→ ShoppingContext 提供 buyer/session 身份
→ BuyerPreference 校验
→ SqlPreferenceStore.append
→ buyer_preferences
```

在另一个 session 读取：

```text
新的 shopping_session_id + 相同 buyer_id
→ Orchestrator 查询买家偏好
→ PreferenceSelector
→ <buyer-preferences> hint
→ MainAgent
→ 可选的 SearchAgent 派发并再次注入同一份记忆
```

撤回：

```text
买家明确撤回偏好
→ MainAgent 复制已存 statement 原文
→ forget_preference_tool
→ 按 buyer 精确删除
→ 后续新 session 不再收到该偏好
```

## 测试

本章新增覆盖：

- 领域对象清理、校验、时间戳和不可变性；
- SQL 往返、顺序、幂等、buyer 隔离和数据库约束；
- remember/forget schema、上下文身份、事件、异常和精确删除；
- dislike 全量保留、like 数量限制、相关性排序和安全回退；
- MainAgent 注入、session 行为、历史纯净性和读取失败；
- 仅向 SearchAgent 注入，以及 buyer 隔离；
- 配置默认值和非法值；
- 经过 composition 和 SQLite 的真实 Agent 工具调用；
- 记住、跨 session 读取、撤回和删除后行为；
- 订单与子 Agent 流程的回归测试。

本章结束时，后端共有 315 项测试通过。

## 已知限制

- 仍然由模型判断一段话是否足够稳定，尚无确定性的用户确认工作流。
- 偏好目前是原子 statement，没有置信度、来源、过期时间等结构化字段。
- 删除只支持精确匹配，不支持语义删除。
- dislike 有意不受数量限制，极端情况下可能生成较长 hint。
- 偏好发生变化后，已经活跃的 Agent session 仍可能在历史状态中保留旧 hint；新 session 一定读取数据库当前状态。旧 hint 替换和状态压缩留给后续强化阶段。
- 暂无 Redis 缓存、分布式失效通知或跨进程记忆事件。

## 下一步

第 19 章将加入 Redis 与异步化，用于缓存、幂等、队列和跨进程事件，同时继续以关系型数据库作为权威数据源。

路线图还新增了第 21 章“代码强化”。在完整理解行为后，最后统一缩短 composition root、减少重复、加强类型与 Lint，并收敛模块边界。
