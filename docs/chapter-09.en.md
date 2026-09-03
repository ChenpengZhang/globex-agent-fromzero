# Chapter 9: Order Transaction Flow

## Goal

This chapter connects the Chapter 8 Order Domain into a deterministic transaction flow that requires no LLM. The Application can now place, query, and cancel orders while maintaining inventory consistency after failures and cancellations.

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

Order capabilities are not exposed as Agent Tools yet. The business flow is validated before the LLM is allowed to invoke it.

## SKU Inventory Rules

`Sku` now has two state-changing domain methods:

- `deduct_stock(quantity)` validates a positive integer and sufficient inventory before deduction.
- `restore_stock(quantity)` validates a positive integer before restoration.

`is_available(quantity)` is a query and returns False for invalid quantities. Deduction and restoration are commands, so invalid operations raise exceptions.

UseCases do not perform `sku.stock -= quantity` directly. Rules such as non-negative stock and positive quantities are protected by the Sku that owns the inventory state.

The in-memory model performs synchronous check-and-deduct operations in one event loop, but it does not provide cross-process locks or database-level concurrency control.

## Product SKU Lookup

`Product.find_sku(sku_id)` encapsulates lookup inside the Product aggregate. A UseCase does not need to know whether Product stores SKUs in a list, dictionary, or another structure.

ProductRepository also gains `find_by_id()`, implemented by InMemoryProductRepository, to support single-product access during ordering.

## InMemoryOrderRepository

The in-memory adapter implements the OrderRepository port from Chapter 8:

- `save(order)` stores or replaces an aggregate by order ID.
- `find_by_id(order_id)` retrieves an order.
- `next_order_id()` produces sequential IDs such as `GBX-000001`.

Replacement allows an order to be updated from CONFIRMED to CANCELLED. The current repository stores Python object references, so mutations to the same object are immediately visible. A real database adapter must explicitly serialize, update, and reload state.

## Application DTOs

Order inputs and outputs live in Application rather than Domain or Presentation.

Inputs include:

- OrderItemInput
- PlaceOrderInput
- QueryOrderInput
- CancelOrderInput

Outputs include:

- MoneyOutput
- AddressOutput
- OrderLineOutput
- OrderOutput

`to_order_output()` converts an Order aggregate into a stable data snapshot. MoneyOutput contains both an integer minor-unit value and a major-unit string, so the Agent and HTTP layers do not calculate monetary values.

DTOs reject blank strings and invalid quantities early at the application boundary. The Domain still retains its own checks so its validity never depends on a particular entry point.

## PlaceOrderUseCase

The place-order UseCase coordinates the Catalog and Order aggregates:

```text
Load Product
→ Check shipping destination
→ Product.find_sku()
→ Sku.deduct_stock()
→ Create an OrderLine price snapshot
→ Generate an order ID
→ Order.place()
→ Save the order
→ Convert to OrderOutput
```

Products, SKUs, prices, and stock all come from deterministic repository-backed objects. They are not supplied or guessed by the Agent. OrderLine captures the checkout title, unit price, and quantity so later catalog price changes cannot alter historical orders.

## Failed-Order Compensation

The UseCase records each `(Sku, quantity)` deducted during the current call. `order_saved` becomes True only after the repository save completes.

The `finally` block runs after success, exceptions, and asynchronous cancellation:

```text
order_saved = True   → keep the deduction
order_saved = False  → restore prior deductions in reverse order
```

A later out-of-stock item, unsupported destination, ID-generation failure, or repository failure therefore cannot leave partial inventory deductions behind.

This is compensation for the in-memory MVP. A real database still needs transactions, isolation, and concurrent update protection. If a remote write succeeds but its response is lost, an in-process flag alone cannot determine the final state.

## Query and Ownership

`load_owned_order()` extracts the access rule shared by Query and Cancel:

- The order must exist, or OrderNotFoundError is raised.
- The buyer must own the order, or OrderAccessDeniedError is raised.

This is an Application access rule, not an Order state invariant, so it does not belong inside the Domain aggregate.

Buyer ID still comes from the HTTP body and session binding, which is not real authentication. A future version must derive identity from a trusted token or server-side security context.

## CancelOrderUseCase

Cancellation resolves all inventory before changing order state:

```text
Load the order and verify ownership
→ Resolve every Product / SKU
→ Order.cancel(reason)
→ Restore inventory for every line
→ Save the CANCELLED order
→ Return OrderOutput
```

If a Product or SKU is missing, the order remains CONFIRMED and no partial restoration occurs. Repeated cancellation is rejected by the Order state machine, preventing duplicate inventory restoration.

The in-memory version does not model a full rollback when saving the cancelled order fails after state change and inventory restoration. The persistence chapter will use a transaction for this boundary.

## Composition Root

Container now owns shared instances of:

- ProductRepository
- OrderRepository
- PlaceOrderUseCase
- QueryOrderUseCase
- CancelOrderUseCase

All order UseCases must share one OrderRepository. Place and Cancel must also share one ProductRepository. Otherwise Query cannot see newly placed orders, and Cancel cannot restore the inventory deducted by Place.

The UseCases are assembled, but MainAgent still has only the read-only product-search tool. This demonstrates that having a business capability and allowing an LLM to invoke it are separate steps.

## Tests and Validation

All 142 tests pass. Chapter 9 adds 63 tests to the 79 from Chapter 8, covering:

- SKU initialization, availability, deduction, restoration, and invalid quantities.
- Product.find_sku and single-ID product repository lookup.
- Sequential order IDs, persistence, retrieval, and replacement.
- Input DTO normalization and freezing, plus output mapping.
- Successful ordering, unsupported destinations, missing products/SKUs, and insufficient stock.
- Inventory restoration after partial failure, save failure, and task cancellation.
- Order queries, buyer isolation, successful cancellation, and repeated cancellation.
- A shared object graph across place/query/cancel in Composition.

## Current Limitations

- Order capabilities are not Agent Tools yet.
- There are no direct order HTTP endpoints.
- Buyer identity is not authenticated.
- In-memory orders and inventory disappear after restart.
- There are no database transactions, cross-process locks, or idempotency keys.
- Payment, shipment, and refund states are outside the current model.

## Next Chapter

Chapter 10 wraps place, query, and cancel UseCases as thin Agent Tools and connects them to MainAgent. Business rules remain in UseCases and Domain; Tools only convert parameters and return results.
