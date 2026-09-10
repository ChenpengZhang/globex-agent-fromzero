# 第十五章：React 前端

## 本章目标

本章增加一个可用的浏览器边界，但不把业务规则搬到浏览器。页面可以提交购物
意图、显示 Agent 流式文本、用最终 HTTP 响应兜底、保留浏览器身份、创建新购物
会话，并展示执行时间线。

为了继续学习持久化和长期记忆，本章前端作为一个完整模块直接实现。它始终只是
现有后端契约的客户端，不会重复实现 Agent、检索或订单流程。

## 运行链路

一次用户对话同时使用两条相互配合的通道：

```text
React 表单
   └── POST /commerce/intents
           └── SubmitIntentInput → MainAgentOrchestrator
                                   └── final_text HTTP 响应

React 事件适配器
   └── WS /commerce/events
           └── session 订阅
               └── token.delta / final.result / error
```

页面会先建立 WebSocket，再允许用户提交 intent。两条请求携带同一个
`shopping_session_id`，进程内事件总线因此只把该会话的事件送到当前页面。

HTTP 响应仍然是权威返回值，同时在 WebSocket 延迟或断开时提供兜底。
`appendFinalTurn()` 会忽略紧邻且内容相同的最终答案，避免 `final.result` 与
`final_text` 把同一条 Agent 回复显示两次。

## 前端结构

```text
frontend/
├── src/
│   ├── App.tsx                    UI 编排与状态
│   ├── api.ts                     HTTP 适配器
│   ├── eventStream.ts             WebSocket 适配器与重连生命周期
│   ├── session.ts                 浏览器身份辅助函数
│   ├── types.ts                   传输与视图契约
│   ├── styles.css                 响应式视觉样式
│   └── components/
│       ├── EventTimeline.tsx       非 token 执行事件
│       ├── ProductCards.tsx        预备的结构化搜索结果
│       └── OrderCard.tsx           预备的结构化订单结果
├── vite.config.ts                 本地 HTTP/WS 代理
└── package.json                   构建与开发命令
```

`App.tsx` 是 Presentation 侧的组装点。它协调浏览器状态并调用适配器，但不知道
商品检索、RAG、库存和订单在后端如何实现。

## 买家身份与购物会话

浏览器在 `localStorage` 中保存两个不同标识：

```text
buyer_id              稳定的浏览器级买家身份
shopping_session_id   一次对话及其 Agent 状态边界
```

刷新页面会保留二者。点击“新对话”时，只替换 shopping session ID 并清空当前
页面；下一次请求会在后端创建全新的 Agent session。buyer ID 保持不变，使第 16
章能够把持久化偏好和历史关联到同一买家。

这些随机 ID 只是学习阶段的标识，不是鉴权令牌。真实身份认证与授权仍属于后续
生产化内容。

## WebSocket 生命周期

`connectEventStream()` 统一管理浏览器 WebSocket，而不是让各个组件直接处理
socket 细节。它会：

1. 根据当前页面选择 `ws://` 或 `wss://`；
2. 连接 `/commerce/events`；
3. socket 打开后发送 session 订阅；
4. 解析并校验收到的事件外壳；
5. 连接关闭后短暂等待并重连；
6. 返回清理函数，用于取消重试计时器并关闭 socket。

session 改变或组件卸载时，React 会调用这个清理函数。这一点在开发模式尤其
重要，因为 React Strict Mode 会故意重复执行 Effect，用来暴露不安全的生命
周期代码。

当前页面在 socket 打开并发出订阅消息后显示“已连接”。第 14 章服务端尚未返回
显式 ready acknowledgement，因此它代表传输层已连接，而不代表已经建立可回放
的事件边界。

## 事件与视图状态

`types.ts` 用可辨识联合类型定义 `TradeEvent`。TypeScript 可以根据
`event.type` 缩小 payload 类型；`isTradeEvent()` 还会做一层运行时外壳校验，
因为网络输入不能只依赖编译期类型断言。

页面按事件职责分别处理：

```text
token.delta    追加临时流式文本
final.result   提交正式 Agent 对话并清空临时文本
error          结束 busy 状态并显示错误提示
其他事件        最多保留 100 条，供执行时间线展示
```

聊天轮次和运行观测事件是两份不同状态。时间线事件不是聊天消息，token delta 也
不会被拆成数百条永久对话记录。

## 商品卡与订单卡

`ProductCards` 和 `OrderCard` 已按未来 `tool.result` 的结构化 payload 实现。
没有这种事件时，它们会有意返回空内容。

当前后端实际只发布 `token.delta`、`final.result` 和 `error`。所以卡片的组件结构
已经准备好，但真实对话里尚不会激活。页面不会解析自由格式的 LLM 文本，也不会
伪造商品或订单数据。后续应在 Tool 边界发布安全的 Application DTO；届时无需
修改 Domain 逻辑即可让这些组件开始渲染。

## Vite 代理

开发时，浏览器从 5173 端口加载页面，FastAPI 运行在 8000 端口。Vite 同时代理
`/commerce` 的 HTTP 与 WebSocket 流量：

```text
browser http://127.0.0.1:5173/commerce/intents
    → FastAPI http://127.0.0.1:8000/commerce/intents

browser ws://127.0.0.1:5173/commerce/events
    → FastAPI ws://127.0.0.1:8000/commerce/events
```

使用同源相对地址，可以避免把 API 地址散落在 React 组件中，也不必为本地开发
专门配置 CORS。

## 可用性与无障碍

当前界面包括：

- 桌面与移动端响应式布局；
- 清晰的连接、处理中和错误状态；
- Enter 发送、Shift+Enter 换行；
- 一轮请求处理中禁止重复提交；
- 示例问题与新对话操作；
- 语义化表单标签、状态角色和对话 live region；
- 显示 buyer/session 后缀，方便观察会话隔离。

本章实际检查了桌面布局和 390 像素宽的移动布局。前端运行期间，浏览器控制台没有
出现应用错误。

## 运行完整流程

在项目根目录启动 FastAPI：

```bash
uv run uvicorn app.presentation.server:build_app --factory
```

在另一个终端启动 Vite：

```bash
cd frontend
npm install
npm run dev
```

访问 `http://127.0.0.1:5173` 并提交购买需求。模型和 embedding 环境变量仍属于
后端配置，需要按主 README 设置。

## 验证结果

本章完成了以下检查：

```text
前端 TypeScript + Vite 生产构建：通过
后端全量回归测试：                  211 passed
桌面与移动浏览器渲染：               通过
```

## 当前限制

- 对话轮次尚未由后端持久化，选择新 session 后不会恢复旧对话。
- WebSocket 能够重连，但没有事件回放或 ready acknowledgement。
- 后端尚未发布结构化 Tool/子 Agent 事件。
- 浏览器生成的 ID 不提供身份认证或权限控制。
- 尚未加入前端组件测试和端到端自动化测试。
- Agent 文本按纯文本渲染，尚未支持 Markdown。

完成这一边界后，第 16 章可以在稳定的 Application 边界之后继续加入持久化、
session 恢复、对话历史和长期买家偏好。
