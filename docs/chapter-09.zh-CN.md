# 跨境 Agent 第九章：订单交易闭环

## 本章目标

本章把第八章的订单 Domain 连接成一条完全确定性、无需 LLM 的交易流程。系统现在可以通过 Application UseCase 下单、查询订单和取消订单，并在失败或取消时维护库存一致性。

```text
Application Input DTO
    ↓
Order UseCase
    ├── Product / Sku
    ├── Order
    └── Repository Ports
    ↓
Application OrderOutput
```

本章仍未把订单能力暴露为 Agent Tool。先验证业务流程，再让 LLM 调用它。

## SKU 库存规则

`Sku` 新增两个改变状态的领域方法：

- `deduct_stock(quantity)` 校验正整数与库存充足后扣减。
- `restore_stock(quantity)` 校验正整数后回补。

`is_available(quantity)` 是查询方法，对非法数量返回 False；扣减和回补是命令，对非法操作抛出异常。

UseCase 不直接执行 `sku.stock -= quantity`。库存不能为负、数量必须为正整数等规则由最了解库存状态的 Sku 保护。

当前内存模型在一个事件循环中执行同步检查和扣减，但还不具备跨进程锁或数据库级并发控制。

## Product 内部 SKU 查找

`Product.find_sku(sku_id)` 封装对聚合内部 SKU 集合的查找。UseCase 不需要知道 Product 使用列表、字典还是其他数据结构保存 SKU。

ProductRepository 同时新增 `find_by_id()`，由 InMemoryProductRepository 实现，为下单流程提供单商品读取能力。

## InMemoryOrderRepository

内存订单仓储实现第八章定义的 OrderRepository：

- `save(order)` 按订单 ID 保存或覆盖聚合。
- `find_by_id(order_id)` 查询订单。
- `next_order_id()` 生成 `GBX-000001` 格式的顺序 ID。

覆盖式保存支持订单从 CONFIRMED 更新为 CANCELLED。当前仓储保存的是 Python 对象引用，因此同一对象的修改会立即可见；真实数据库适配器需要显式序列化、更新和重新加载。

## Application DTO

订单输入与输出被定义在 Application，而不是 Domain 或 Presentation。

输入包括：

- OrderItemInput
- PlaceOrderInput
- QueryOrderInput
- CancelOrderInput

输出包括：

- MoneyOutput
- AddressOutput
- OrderLineOutput
- OrderOutput

`to_order_output()` 将 Order 聚合转换成稳定的数据快照。MoneyOutput 同时提供最小单位整数与主单位字符串，Agent 和 HTTP 不需要自行计算金额。

DTO 在应用边界尽早拒绝空字符串和非法数量；Domain 仍保留自身校验，使领域对象不依赖某一个入口的正确性。

## PlaceOrderUseCase

下单 UseCase 协调 Catalog 与 Order 两个聚合：

```text
读取 Product
→ 检查配送国家
→ Product.find_sku()
→ Sku.deduct_stock()
→ 创建 OrderLine 价格快照
→ 生成订单 ID
→ Order.place()
→ 保存订单
→ 转换为 OrderOutput
```

Product、SKU、价格和库存全部来自仓储中的确定性对象，不由 Agent 提供或猜测。OrderLine 捕获下单时的标题、单价与数量，商品以后调价不会改变历史订单。

## 下单失败补偿

UseCase 记录本次调用已经扣减的 `(Sku, quantity)`。只有订单保存成功后，`order_saved` 才设置为 True。

`finally` 在成功、异常和异步任务取消时都会执行：

```text
order_saved = True   → 保留库存扣减
order_saved = False  → 按相反顺序回补已扣库存
```

因此后续商品库存不足、配送失败、订单号生成失败或保存失败，都不会留下部分库存扣减。

这是当前内存 MVP 的补偿机制。真实数据库还需要事务、隔离级别和并发更新保护；如果远程写入已发生但响应丢失，仅靠进程内 flag 无法判断最终状态。

## 查询与订单所有权

`load_owned_order()` 提取 Query 与 Cancel 共用的访问规则：

- 订单必须存在，否则抛出 OrderNotFoundError。
- buyer 必须与订单所有者一致，否则抛出 OrderAccessDeniedError。

这是 Application 访问规则，不是 Order 状态不变量，因此没有放入 Domain 聚合。

当前 buyer ID 仍来自 HTTP 请求正文和 session 绑定，尚不是真正认证。未来应从可信 Token 或服务端身份上下文获取。

## CancelOrderUseCase

取消流程先解析所有需要回补的库存，再改变订单状态：

```text
读取并验证订单所有权
→ 找齐全部 Product / SKU
→ Order.cancel(reason)
→ 回补每条订单行的库存
→ 保存 CANCELLED 订单
→ 返回 OrderOutput
```

如果商品或 SKU 缺失，订单仍保持 CONFIRMED，库存也不会部分恢复。重复取消由 Order 状态机拒绝，因此不能重复增加库存。

当前内存版本没有模拟“状态改变和库存回补后，保存取消结果失败”的完整回滚。持久化章节会使用事务处理这一边界。

## Composition Root

Container 现在持有共享的：

- ProductRepository
- OrderRepository
- PlaceOrderUseCase
- QueryOrderUseCase
- CancelOrderUseCase

三个订单 UseCase 必须使用同一个 OrderRepository，下单和取消也必须使用同一个 ProductRepository。否则查询看不到下单结果，取消也无法回补原库存。

订单 UseCase 已经被组装，但 MainAgent 工具箱仍只有只读商品搜索。这证明“业务能力已经存在”与“允许 LLM 调用业务能力”是两个独立步骤。

## 测试与验收

全套共 142 项测试，全部通过。本章在第八章的 79 项基础上新增 63 项，覆盖：

- SKU 库存初始化、查询、扣减、回补和非法数量。
- Product.find_sku 与商品仓储单 ID 查询。
- 订单仓储的顺序 ID、保存、查询和覆盖更新。
- 输入 DTO 规范化、冻结和输出 DTO 映射。
- 成功下单、配送失败、商品/SKU 缺失和库存不足。
- 部分扣减失败、保存失败和任务取消时的库存回补。
- 查询订单、buyer 隔离、正常取消和重复取消。
- Composition 中下单、查询、取消共享同一对象图。

## 当前限制

- 订单能力尚未包装为 Agent Tools。
- HTTP 还没有直接订单端点。
- buyer ID 尚未经过真正身份认证。
- 内存订单和库存会在进程重启后消失。
- 没有数据库事务、跨进程锁和幂等键。
- 没有支付、物流、退款等后续状态。

## 下一章

第十章把下单、查询和取消 UseCase 包装成薄 Agent Tools，并接入 MainAgent。业务规则仍保留在 UseCase 与 Domain，Tool 只负责参数转换和结果返回。
