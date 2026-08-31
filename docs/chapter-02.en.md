# Chapter 2: Catalog Domain and Repository

## Goal

This chapter turns a product from unstructured model-generated text into an explicitly defined domain model. The Agent does not use these objects yet; the catalog business model must work independently of the LLM first.

The dependency direction introduced in this chapter is:

```text
Infrastructure
    │ implements
    ▼
ProductRepository (Domain port)
    │ returns
    ▼
Product → Sku → Money
```

## Domain Objects

### Money Value Object

`Money` stores both a minor-unit amount and a currency:

```python
Money(amount_minor=18900, currency="CNY")
```

This represents `189.00 CNY`. Storing an integer minor-unit amount avoids floating-point errors in price and order calculations.

Money has no independent identity. Its business meaning is determined by `amount_minor + currency`, so it is a Value Object rather than an Entity.

### Sku Entity

`Sku` represents a purchasable product variant and contains:

- `sku_id`
- A specification description
- A price
- Stock

`is_available()` encapsulates the domain rule for checking whether stock can satisfy a requested quantity.

### Product Aggregate Root

`Product` is the entry point to the catalog aggregate. A Product can contain multiple SKUs, and external code accesses the aggregate through methods such as `primary_sku()`.

`searchable_text()` combines the title, brand, category, description, and SKU specifications into a consistent text representation for the keyword search introduced in the next chapter.

## Repository Port and Adapter

`ProductRepository` belongs to the Domain because it defines the product-access capability required by the business without selecting a storage technology.

`InMemoryProductRepository` belongs to Infrastructure because it chooses a Python dictionary as the concrete storage mechanism. SQL, HTTP, or other implementations can be added later without changing the Domain or the Application code that depends on the port.

```text
ProductRepository              what the business needs
InMemoryProductRepository      how the current environment provides it
```

This is dependency inversion: the inner layer defines the port, and an outer layer implements it.

## Seed Data

`build_seed_products()` creates three products for development and testing. Seed data belongs to Infrastructure because it describes how the current environment obtains initial data; it is not an invariant that every Product must follow.

## Files Added

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

## Acceptance Checks

The chapter is complete when:

- `Money.from_major_units(189, "CNY")` produces `amount_minor == 18900`.
- `Money.to_major_units()` converts the amount back to `189`.
- Lowercase currency codes are normalized to uppercase.
- Negative money and stock values are rejected.
- The seed builder creates 3 Product objects.
- The Repository preserves requested ID order and ignores unknown IDs.
- The Domain does not depend on AgentScope, FastAPI, or a concrete database.

## Current Validation Status

This chapter now passes validation:

- The project compiles successfully.
- `Money.from_major_units(189, "cny")` correctly produces `18900` minor units in CNY.
- `Money.to_major_units()` correctly converts the amount back to `189`.
- Negative monetary amounts are rejected by the domain validation.
- The seed builder creates 3 products.
- The in-memory Repository reads all products, preserves requested ID order, and ignores unknown IDs.

## Next Chapter

The next chapter introduces `CatalogSearchUseCase` with deterministic keyword matching and no LLM dependency. This demonstrates that catalog search is an ordinary application capability and that an Agent tool is only an adapter around it.
