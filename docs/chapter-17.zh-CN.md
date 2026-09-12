# 第十七章：关系型数据库持久化

## 本章目标

第 16 章已经用 JSON 和 JSONL 文件验证了持久化流程。本章保持相同的 Domain 端口
和 Application 编排，把文件 Adapter 替换为基于 SQLite 的异步 SQLAlchemy
Adapter。

本章重点学习关系型持久化的几个核心概念：

- 异步数据库 Engine 与连接生命周期；
- 明确的表、主键、外键、约束和索引；
- Store 操作的事务边界；
- Domain record 与 ORM row 之间的映射；
- 启动时建表和关闭时释放资源；
- 通过全新的数据库连接验证重启恢复。

本章暂不持久化订单、库存、向量数据和长期买家偏好。

## 稳定端口与可替换 Adapter

最重要的架构结果是：Agent 流程和历史 UseCase 都不需要改变。

```text
SessionRegistry
    → SessionStore
        ├── JsonFileSessionStore       第 16 章
        └── SqlSessionStore            第 17 章

GetConversationHistoryUseCase
    → ConversationStore
        ├── JsonFileConversationStore  第 16 章
        └── SqlConversationStore       第 17 章
```

端口继续位于 Domain。SQLAlchemy、SQLite 类型、SQL 语句和 ORM row 都位于
Infrastructure，Composition Root 决定运行时使用哪一个实现。

这就是依赖倒置在当前项目中的实际价值：更换存储技术时，不需要修改
`SessionRegistry`、`MainAgentOrchestrator`、历史 UseCase、FastAPI DTO 或 React。

## 数据库依赖

当前使用：

```text
SQLAlchemy 2.x asyncio API   ORM、SQL 构造、事务与 Engine
aiosqlite                    SQLite 异步 DBAPI driver
```

数据库 URL 同时表达了两层选择：

```text
sqlite+aiosqlite:///relative/path.db
sqlite+aiosqlite:////absolute/path.db
sqlite+aiosqlite:///:memory:
```

`sqlite` 是 SQL dialect，`aiosqlite` 是异步 driver。本章明确拒绝其他 URL，避免
一份包含 SQLite 专用行为的实现假装成数据库无关方案。

## Engine、Session 与事务

这三个 SQLAlchemy 概念承担不同职责：

```text
AsyncEngine
    管理数据库配置和连接池

AsyncSession
    提供一次 SQL/ORM 工作单元的上下文

Transaction
    让一组操作全部提交，或者全部回滚
```

Engine 的生命周期与整个应用一致，由 Composition Root 创建一次。
`async_sessionmaker` 也只创建一次，并注入两个 SQL Store。每个 Store 方法再从
Factory 获取一个短生命周期 `AsyncSession`。

Store 接收 Session Factory，而不是共享一个 Session。原因是 `AsyncSession` 内部
保存着可变的 unit-of-work 状态，不能被互不相关的并发请求共同使用。

## SQLite Engine 配置

`create_database_engine()` 创建 `AsyncEngine`，并在它的同步 facade 上注册连接
listener。每个新 SQLite 连接都会执行：

```sql
PRAGMA foreign_keys=ON;
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
```

三项配置分别负责：

```text
foreign_keys   真正执行父子表引用约束，而不是静默忽略
WAL            writer 提交时仍允许 reader 继续读取
busy_timeout   遇到临时写锁时最多等待 5 秒
```

WAL 能改善读写共存，但不会把 SQLite 变成无限并发写数据库；SQLite 仍然会串行化
写操作。

`bootstrap_schema()` 会为文件数据库创建缺失的父目录，然后在 Engine 事务中调用
`Base.metadata.create_all()`。重复调用不会删除已有数据。

`create_all()` 只是 schema bootstrap，不是迁移系统。它能创建缺失表，却不能可靠
地修改已有列和约束。生产阶段需要 Alembic 或其他显式 migration 流程。

## 关系型 Schema

本章增加四张表：

```text
conversation_sessions
    ├── conversation_messages
    └── conversation_events

agent_session_states
```

### `conversation_sessions`

一行代表一次购物对话的可读 metadata 和所有权边界：

```text
session_id      主键
buyer_id        owner 查询字段
locale          最新 session locale
currency        最新 session currency
created_at      初次创建时间
last_active_at  最近 touch 时间
```

message 和 event 通过外键引用该表。开启 SQLite 外键后，未知 conversation 不能拥有
message 或 event。

### `conversation_messages`

每行保存一个可读的 buyer 或 Agent turn。它既有全局代理主键 `id`，也有当前对话
内部的 `turn_index`。

`(session_id, turn_index)` 具有唯一约束，因此同一对话中不能有两行占据相同位置；
不同对话则都可以拥有 turn 0。

显式复合索引表达并支持按 session 顺序读取。SQLite 也可能为唯一约束建立内部索引；
生产阶段可以通过 query plan 和实际测量判断是否需要同时保留二者。

### `conversation_events`

Event 与聊天消息继续分表保存。payload 使用 SQLAlchemy `JSON` 类型，能够保留 Tool、
error 和 final result 的结构化数据，而不会把执行观测混成用户可见的聊天内容。

### `agent_session_states`

该表保存 `SessionRegistry` 使用的不透明序列化快照。快照内部已经包含第 16 章定义的
buyer 所有权外壳。

它没有指向 `conversation_sessions` 的外键。`SessionStore` 与 `ConversationStore` 是
独立端口，所以保存 Agent state 不应依赖对话记录必须先成功。

## 可移植的自增主键

Message 和 event ID 使用：

```python
BigInteger().with_variant(Integer, "sqlite")
```

生产数据库常用 `BIGINT` 保存持续增长的 ID；但 SQLite 的 rowid 自增语义要求类型名
必须是 `INTEGER PRIMARY KEY`。这个 variant 让其他 dialect 继续使用预期的大整数，
同时为 SQLite 生成兼容类型。

## `SqlSessionStore`

Agent 快照具有覆盖语义：一个 session 只保留当前快照。因此 `save()` 使用 SQLite
原生 UPSERT：

```text
INSERT 新 session state
    ON CONFLICT(session_id)
    DO UPDATE snapshot_json 和 updated_at
```

它是一条原子 SQL，不需要先查询“数据是否存在”。在 Infrastructure 中使用
`sqlalchemy.dialects.sqlite.insert` 是合理的，因为这个 Adapter 本来就是 SQLite
专用实现。

冲突更新中需要显式设置 `updated_at`。普通 Column 的 `onupdate` 不会自动应用到
SQLite `ON CONFLICT DO UPDATE` 的 `set_` 内容。

`load()` 使用 `AsyncSession.get()`，因为 `session_id` 就是主键。Store 返回 Domain
端口要求的不透明 JSON 字符串，不会把 ORM row 返回给上层。

## `SqlConversationStore`

### Touch session metadata

`touch_session()` 按主键读取 session row：不存在则新增；buyer 相同则更新 locale、
currency 和活跃时间；buyer 不同则拒绝。`session_factory.begin()` 在正常结束时提交，
所有权异常则自动回滚。

### 追加 turns

`append_turn()` 查询当前 session 最大的 `turn_index`，并把新 turn 写到下一个位置：

```text
没有旧 turn      → 0
最大 index 为 0  → 1
最大 index 为 17 → 18
```

当前 Orchestrator 的 per-session lock 保证单进程内该计算串行执行；数据库唯一约束
提供最后一道完整性检查。跨进程编号仍需要生产级策略。

### 读取最新 turns

为了高效返回最新 `limit` 条，SQL 先按 `turn_index DESC` 排序并应用 limit；Python
再反转这个小结果，使调用方得到正常阅读顺序：

```text
数据库结果  turn 9, turn 8, turn 7
返回历史    turn 7, turn 8, turn 9
```

先 limit 再 reverse，避免每次加载整段长对话。

### 批量追加 events

`append_events()` 先确认一批 event 属于同一 session，然后在一个事务内统一添加。
如果其中一个 JSON payload 无法序列化，整批都会回滚，不会提交半截 trace。

### 时间戳映射

Domain record 使用带时区的 ISO 字符串。即使声明 `DateTime(timezone=True)`，SQLite
读取时仍可能返回 naive `datetime`。Adapter 因此会把输入统一为 UTC，并在映射回
Domain record 时恢复明确的 UTC offset。

这类转换用于处理数据库表示差异，所以属于 Adapter 职责。

## Composition 与生命周期

配置可以提供 `DATABASE_URL`；如果为空，默认使用：

```text
<解析后的 DATA_DIR>/globex.db
```

Composition Root 创建一个 Engine 和一个 Session Factory，再把同一个 Factory
注入 `SqlSessionStore` 与 `SqlConversationStore`。

应用启动时先执行 schema bootstrap，再开始处理请求；关闭时使用嵌套 `finally`，
即使向量资源清理失败，也会继续 dispose 数据库 Engine。

当前生产运行路径为：

```text
FastAPI/CLI 启动
    → bootstrap SQLite schema
    → 启动向量与知识资源

请求
    → Orchestrator
        → SqlSessionStore
        → SqlConversationStore

FastAPI/CLI 关闭
    → 关闭向量资源
    → dispose AsyncEngine
```

## 重启恢复证明

集成测试不是简单地让两个 Store 共享仍然存活的对象，而是：

1. 创建第一个 Engine 并完成一轮 Agent 对话；
2. 保存 AgentState、conversation metadata、messages 和 events；
3. 完全 dispose 第一个 Engine；
4. 针对同一个数据库文件创建第二套 Engine、Session Factory、Store 和
   SessionRegistry；
5. 验证 Agent context 和可读历史都能恢复。

这证明数据跨越了连接和对象生命周期，与后端进程重启时的核心边界相同。

## JSON 文件与 SQLite 对比

```text
关注点                  第 16 章文件              第 17 章 SQLite
----------------------  ------------------------  ----------------------------
快照覆盖                覆盖单个 JSON 文件         主键 UPSERT
对话写入                追加 JSONL 行              事务 INSERT row
所有权查询              扫描最后一条 metadata      主键索引查询
历史 limit              读取文件后切片              SQL ORDER BY + LIMIT
数据完整性              Application 检查           外键与唯一约束
批量原子性              不保证                     数据库事务
并发访问                较弱                       锁等待与约束
Schema 演进             隐式 record 形态            显式 schema（尚无 migration）
```

文件 Adapter 仍然可以作为测试或参考实现保留。Composition Root 切换实现，并不要求
删除它们。

## 验证结果

完成后的实际检查结果：

```text
后端全量回归测试：267 passed
```

测试覆盖：

- schema bootstrap 幂等和已有数据保留；
- 自动创建缺失的数据库父目录；
- SQLite PRAGMA 配置；
- 外键和 turn 唯一约束；
- 快照 insert、load、UPSERT 与更新时间；
- conversation metadata 所有权与刷新；
- 最新 N 条历史的顺序和 UTC 规范化；
- 结构化 event 持久化与事务回滚；
- 默认和显式数据库配置；
- FastAPI/Container 生命周期兼容；
- 通过全新 Engine 恢复 AgentState 和可读历史。

## 当前限制

- 只支持 `sqlite+aiosqlite` URL。
- `create_all()` 不能代替真正的 schema migration 工具。
- `max(turn_index) + 1` 只由进程内 lock 保护，没有分布式编号或重试策略。
- WAL 仍然只允许一个 writer 同时写入。
- 第 16 章已有 JSON/JSONL 文件不会自动导入。
- 订单、库存和商品 Repository 仍然位于内存。
- Conversation events 已持久化，但还不能通过 API 查询或回放。
- 尚无保留、归档、备份、静态加密和数据库观测策略。
- buyer ID 仍然是客户端提供的标识，不是认证后的 principal。

第 18 章可以在可靠持久化之上加入长期买家记忆，同时继续把 preference 与单个
session 的 AgentState、conversation history 分开管理。
