# 跨境Agent第二章
## 本章新增实现的功能
- Money对象：商品价格普通值到标准值的双向转换，标准值采用分（cents），去除浮点精度误差。

- SKU实体

- Product聚合类

- Repository端口和infrastructure层实现

## 补充：本章目标

本章把“商品”从大模型可能生成的一段文本，转变为由业务代码严格定义的领域对象。Agent 暂时还没有接触这些对象；我们先确保商品业务能够脱离 LLM 独立成立。

本章形成的依赖关系是：

```text
Infrastructure
    │ 实现
    ▼
ProductRepository（Domain 端口）
    │ 返回
    ▼
Product → Sku → Money
```

## 领域对象

### Money 值对象

`Money` 同时保存最小货币单位和币种，例如：

```python
Money(amount_minor=18900, currency="CNY")
```

它表示 `189.00 CNY`。使用整数保存最小单位，可以避免 `float` 在金额计算中的精度误差。

`Money` 没有独立 ID，它通过 `amount_minor + currency` 的值表达业务含义，因此属于 Value Object，而不是 Entity。

### Sku 实体

`Sku` 表示具体可售规格，包含：

- `sku_id`
- 规格描述
- 价格
- 库存

`is_available()` 把“库存能否满足指定数量”封装为领域行为。

### Product 聚合根

`Product` 是商品聚合的入口。一个 Product 可以包含多个 SKU，外部通过 `primary_sku()` 等方法访问聚合内部对象。

`searchable_text()` 将标题、品牌、品类、描述和 SKU 规格组合为可检索文本，为下一章的关键词检索提供统一输入。

## Repository 端口与适配器

`ProductRepository` 位于 Domain，因为它定义领域层需要的商品访问能力，而不规定存储技术。

`InMemoryProductRepository` 位于 Infrastructure，因为它选择 Python 字典作为具体存储方式。以后可以增加 SQL、HTTP 或其他实现，而不改变 Domain 和 Application 对端口的依赖。

```text
ProductRepository              业务需要什么
InMemoryProductRepository      当前用什么技术实现
```

这体现了依赖倒置：内层定义端口，外层实现端口。

## 种子数据

`build_seed_products()` 构造三件用于开发和测试的商品。种子数据属于 Infrastructure，因为它描述当前运行环境如何准备初始数据，不属于商品本身必须遵守的领域规则。

## 本章文件

```text
app/domain/catalog/
├── money.py
├── sku.py
├── product.py
└── ports/
    └── product_repository.py

app/infrastructure/persistence/
├── in_memory_product_repository.py
└── seed_products.py
```

## 验收方式

本章完成时应满足：

- `Money.from_major_units(189, "CNY")` 得到 `amount_minor == 18900`。
- `Money.to_major_units()` 能还原为 `189`。
- 小写币种能够规范化为大写。
- 负金额和负库存被拒绝。
- 种子数据能够生成 3 个 Product。
- Repository 能按传入 ID 的顺序返回商品，并忽略未知 ID。
- Domain 不依赖 AgentScope、FastAPI 或具体数据库。

## 当前验收状态

本章验证通过：

- 项目可以通过 Python 编译。
- `Money.from_major_units(189, "cny")` 正确得到 `18900 CNY` 最小单位。
- `Money.to_major_units()` 正确还原为 `189`。
- 负金额会被领域校验拒绝。
- 种子数据能够生成 3 个商品。
- 内存 Repository 能读取全部商品、保持指定 ID 的查询顺序，并忽略未知 ID。

## 下一章

下一章实现 `CatalogSearchUseCase`，先使用确定性的关键词匹配完成商品搜索，不依赖 LLM。这样可以证明搜索是普通应用业务能力，Agent 工具只负责调用它。

