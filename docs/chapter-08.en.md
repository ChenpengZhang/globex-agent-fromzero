# Chapter 8: Order Domain Model

## Goal

This chapter builds an order Domain that is independent of the Agent, HTTP, and database layers. An order can now represent a shipping-address snapshot, product-line snapshots, monetary calculations, and valid lifecycle transitions.

```text
Order aggregate
└── Order (aggregate root)
    ├── Address (immutable value object)
    └── OrderLine × N (immutable order-line snapshots)
        └── Money (immutable monetary value object)
```

This chapter does not implement order UseCases, Agent Tools, or a repository adapter. The Domain contains only business concepts, rules, and required ports.

## Money Operations

`Money` now provides `add()` and `multiply()` for order-line subtotals and order totals.

- Only amounts in the same currency can be added.
- Money can only be multiplied by a non-negative integer.
- Every operation returns a new Money object.
- Although `bool` is an `int` subclass in Python, it is not accepted as a quantity.

The Domain therefore owns monetary calculation. The Agent and Application layers do not manipulate `amount_minor` directly or perform floating-point price calculations.

## Address Value Object

`Address` represents the shipping-address snapshot captured when an order is placed. It has no independent identity, so equality is determined by its field values.

Its rules are:

- Required address fields cannot be blank.
- Country is normalized to a two-letter uppercase code.
- `state` may be empty for locations that do not use a state or province.
- Surrounding whitespace is removed.
- `frozen=True` prevents a historical order address from changing.

A saved customer address may change later, but an Address inside an order remains the historical checkout snapshot. Similar fields do not imply the same lifecycle or business meaning.

## OrderLine Snapshot

`OrderLine` stores the product ID, SKU ID, title, checkout unit price, and quantity. Later catalog price or title changes cannot alter an existing order.

An order line guarantees that:

- Product identifiers and title are present.
- Quantity is a positive integer.
- The line is immutable.
- `subtotal()` delegates calculation to `Money.multiply()`.

The MVP does not independently query or persist lines, so there is no `OrderLineRepository` or separate `line_id`.

## Order Aggregate Root

`Order` is the single entry point to the aggregate. It stores the buyer, shipping address, lines, and status while enforcing rules that span its internal objects.

Construction invariants include:

- Order ID and buyer ID must be present.
- An order must contain at least one line.
- Every line must use the same currency.
- The incoming line sequence is converted to a tuple so later mutation of the caller's list cannot change the aggregate.

Address and OrderLine are frozen snapshots. Order itself must change lifecycle state, so it is not frozen. State changes must go through business methods on the aggregate root.

## Order State Machine

```text
DRAFT ── confirm() ──> CONFIRMED ── cancel(reason) ──> CANCELLED
```

- A newly constructed order starts in DRAFT.
- Only a DRAFT order can be confirmed.
- Only a CONFIRMED order can be cancelled.
- Cancellation requires a non-blank reason.
- Confirmation and cancellation record UTC timestamps.
- Confirmed or cancelled orders cannot repeat the corresponding operation.

`Order.place()` represents the point at which the customer has already confirmed the purchase in the Agent conversation. It constructs the order, calls `confirm()`, and returns a CONFIRMED order. The ordinary constructor retains DRAFT so the complete state machine remains explicit.

## An Aggregate Is Not One Class

Address and OrderLine remain part of the Order aggregate even though they live in separate files. An aggregate defines a consistency and persistence boundary; it does not require every field to be placed in one Python class.

Flattening address fields and multiple product lines into Order would create parallel-list alignment problems, concentrate unrelated rules in one large class, and make snapshot immutability difficult to express. With composition, each object owns the rule it understands best:

```text
Address       Address validity
OrderLine     Quantity and subtotal
Money         Monetary operations
Order         Whole-order invariants and lifecycle
```

They are still persisted as one unit through `OrderRepository.save(order)`. Address and OrderLine do not receive independent repositories.

## OrderRepository Port

The Domain defines the storage capabilities required by the Application:

- `save(order)` persists an aggregate.
- `find_by_id(order_id)` retrieves an order.
- `next_order_id()` generates the next order ID.

The port does not choose memory, PostgreSQL, or another storage technology. Concrete adapters belong to Infrastructure. The MVP follows the original project's simplified design by placing ID generation on OrderRepository; a larger system could extract an independent OrderIdGenerator port.

## Domain and Output Formats

This chapter does not copy the original project's `snapshot()` method onto Order. The Domain does not need to understand HTTP JSON or Agent Tool response formats. The next chapter will use Application DTOs to produce stable output data from an Order.

## Tests and Validation

All 79 tests pass. Chapter 8 adds 42 tests covering:

- Same-currency Money operations, invalid multipliers, and immutability.
- Address normalization, required fields, country codes, and immutability.
- OrderLine snapshot fields, quantity rules, and subtotal calculation.
- Order identity, empty orders, mixed currencies, and isolation from caller list mutation.
- Confirmation, cancellation, invalid transitions, and timestamp recording.
- Multi-line totals and `Order.place()`.

## Current Limitations

- There is no concrete OrderRepository adapter yet.
- Place, lookup, and cancellation UseCases do not exist yet.
- Inventory is not checked or decremented.
- Payment, shipment, and refund states are outside the MVP.
- Orders are not yet exposed to the Agent or HTTP API.

## Next Chapter

Chapter 9 builds the order Application flow with an InMemoryOrderRepository, place/get/cancel UseCases, and Application DTOs. Chapter 10 will wrap those UseCases as Agent Tools so business workflow and LLM tool calling are introduced separately.
