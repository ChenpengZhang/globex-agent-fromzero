# 跨境 Agent 第八章：订单领域模型

## 本章目标

本章建立与 Agent、HTTP 和数据库无关的订单 Domain。订单现在能够表达收货地址快照、商品行快照、金额计算和合法的生命周期变化。

```text
Order 聚合
└── Order（聚合根）
    ├── Address（不可变值对象）
    └── OrderLine × N（不可变订单行快照）
        └── Money（不可变金额值对象）
```

本章没有实现下单 UseCase、Agent Tool 或仓储适配器。Domain 只负责业务概念、规则和所需端口。

## Money 领域运算

`Money` 新增 `add()` 和 `multiply()`，为订单行小计和订单总价提供可靠计算。

- 金额只能与相同币种相加。
- 金额只能乘以非负整数。
- 运算返回新的 Money，不修改原对象。
- `bool` 虽然是 Python 的 `int` 子类，但不能作为商品数量。

因此金额计算由 Domain 完成，Agent 和 Application 不需要直接操作 `amount_minor`，也不能自行进行浮点数计算。

## Address 值对象

`Address` 表示下单时的收货地址快照。它没有独立 ID，其相等性由字段值决定，因此是值对象。

关键规则：

- 关键地址字段不能为空。
- 国家使用两位大写代码。
- `state` 可以为空，以兼容不使用州或省的地区。
- 所有文本清理首尾空格。
- `frozen=True` 防止历史订单地址被修改。

用户地址簿中的地址以后可以修改，但订单中的 Address 是下单时复制的历史快照。两者即使字段相似，生命周期和业务含义也不同。

## OrderLine 订单行快照

`OrderLine` 保存 `product_id`、`sku_id`、标题、下单单价和数量。商品目录以后调价或改名，不会影响已经创建的订单。

订单行保证：

- 商品标识与标题不能为空。
- 数量必须为正整数。
- 订单行不可变。
- `subtotal()` 委托给 `Money.multiply()` 计算小计。

当前 MVP 不需要独立查询或保存订单行，因此没有 `OrderLineRepository`，也没有单独的 `line_id`。

## Order 聚合根

`Order` 是聚合的唯一入口。它保存买家、收货地址、订单行和状态，并负责跨多个内部对象的一致性。

创建时的不变量：

- order ID 和 buyer ID 不能为空。
- 至少包含一条订单行。
- 所有订单行必须使用相同币种。
- 外部传入的行序列会转换为 tuple，避免外部列表在订单创建后改变聚合。

`Address` 和 `OrderLine` 是冻结快照，而 `Order` 本身需要改变状态，因此 Order 不使用 `frozen=True`。状态变化必须经过聚合根的业务方法。

## 订单状态机

```text
DRAFT ── confirm() ──> CONFIRMED ── cancel(reason) ──> CANCELLED
```

- 新构造的订单处于 DRAFT。
- 只有 DRAFT 可以确认。
- 只有 CONFIRMED 可以取消。
- 取消必须提供非空原因。
- 确认和取消分别记录 UTC 时间。
- 已确认或已取消订单不能重复执行对应操作。

`Order.place()` 表示用户已经在 Agent 对话中明确确认下单，因此它创建订单后立即执行 `confirm()`，返回 CONFIRMED 订单。普通构造器仍保留 DRAFT，以完整表达状态机。

## 聚合不等于一个类

Address 和 OrderLine 虽然在独立文件中，仍属于 Order 聚合。聚合描述的是一致性和持久化边界，而不是要求把所有字段写进一个 Python 类。

如果把地址字段和多条商品行全部展开到 Order，会出现并行列表错位、规则集中在一个大类、快照可变性难以表达等问题。拆分后，每个对象负责最了解的规则：

```text
Address       地址是否合法
OrderLine     商品数量与小计
Money         金额运算
Order         整张订单与状态转换
```

它们仍然作为一个整体通过 `OrderRepository.save(order)` 保存，不会分别建立 Address 或 OrderLine 仓储。

## OrderRepository 端口

Domain 定义了 Application 所需的仓储能力：

- `save(order)` 保存订单聚合。
- `find_by_id(order_id)` 查找订单。
- `next_order_id()` 生成下一个订单 ID。

端口没有决定使用内存、PostgreSQL 或其他存储。具体实现属于 Infrastructure。当前 MVP 沿用原项目的简化方案，将 ID 生成放在 OrderRepository；规模扩大后可以拆成独立的 OrderIdGenerator 端口。

## Domain 与输出格式

本章没有照搬原项目 Order 上的 `snapshot()`。Domain 不需要知道 HTTP JSON 或 Agent Tool 的返回格式。下一章会使用 Application DTO 将 Order 转换为稳定的输出数据。

## 测试与验收

全套共 79 项测试，全部通过。本章新增 42 项测试，覆盖：

- Money 的同币种运算、非法乘数和不可变性。
- Address 的字段标准化、必填规则、国家代码和不可变性。
- OrderLine 的快照字段、数量规则和小计。
- Order 的身份字段、空订单、混合币种和外部列表隔离。
- 确认、取消、非法状态转换与时间记录。
- 多行订单总价和 `Order.place()`。

## 当前限制

- 尚无 OrderRepository 的具体实现。
- 尚无下单、查询和取消 UseCase。
- 没有库存检查或扣减。
- 没有支付、物流和退款状态。
- 订单还未暴露给 Agent 或 HTTP API。

## 下一章

第九章进入订单 Application 流程：实现 InMemoryOrderRepository、下单/查询/取消 UseCase 和 Application DTO。第十章再把这些用例包装成 Agent Tools，避免同时学习业务流程与 LLM 工具调用。
