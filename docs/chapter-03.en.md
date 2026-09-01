# Chapter 3: Deterministic Catalog Search

## Goal

This chapter introduces catalog search without any LLM dependency. Search is first implemented as an ordinary application capability; a later Agent tool will only translate model arguments into a `ProductSearchSpec` and invoke this use case.

```text
ProductSearchSpec
        ↓
CatalogSearchUseCase
        ↓
ProductRepository
        ↓
Keyword recall → business filters → ranking → Top-K → product cards
```

## ProductSearchSpec

`ProductSearchSpec` is a value object describing one search request. It centralizes normalization and validation:

- Leading and trailing whitespace is removed from the query and category.
- Shipping destinations are normalized to uppercase two-letter country codes.
- Target currencies are normalized to uppercase three-letter codes.
- The price cap is normalized to `Decimal`.
- `top_k` is restricted to a valid range.
- Empty queries, negative budgets, and invalid codes are rejected.

`raw_query` will represent the user's original wording, while `normalized_query` represents the keywords used for retrieval. The caller supplies it directly in this chapter; a future Agent will extract it from natural language.

## CatalogSearchUseCase

The use case belongs to the Application layer and coordinates a complete search:

1. Load products through `ProductRepository`.
2. Tokenize the query and searchable product text.
3. Calculate a base score from matching terms.
4. Apply a one-time three-point category boost.
5. Apply shipping destination, currency, and price-cap constraints.
6. Sort candidates by descending score.
7. Select Top-K results and create serializable product cards.

The keyword algorithm is currently a private use-case implementation. It is not a permanent core-domain rule. When vector retrieval is introduced, the replaceable retrieval capability will be extracted behind a port and implemented by Infrastructure.

## Chinese 2-Gram Tokens

Chinese text commonly contains no spaces. Splitting “旅行装备” only on whitespace would produce one long token, so the MVP also creates consecutive two-character fragments:

```text
旅行装备
→ 旅行, 行装, 装备
```

This provides a deterministic keyword-retrieval baseline. It is not intended to replace production Chinese tokenization or semantic retrieval.

## Soft and Hard Constraints

`category` is currently a soft constraint: a match increases the ranking score but does not immediately exclude close candidates from other categories.

The following are hard constraints:

- Unsupported destination: `ship_to_unavailable`
- Unsupported target currency: `currency_unsupported`
- Price over budget: `over_price_cap`

Rejected candidates are not silently discarded. They are returned through `filtered_out`, allowing a future Agent to distinguish “nothing was found” from “a product was found but rejected by a constraint.”

## Result Structure

The use case returns:

```text
hits                 Top-K product cards satisfying all hard constraints
filtered_out         summaries of keyword matches rejected by constraints
total_candidates     accepted candidates before Top-K truncation
recall_strategy      currently fixed to keyword_2gram
```

The Domain continues to store exact monetary values with `Money`. Values are converted into JSON-friendly major-unit numbers only at the Application output boundary.

## Test Coverage

The chapter contains 13 passing tests covering:

- SearchSpec normalization.
- Empty queries, invalid Top-K values and country codes, negative budgets, and non-numeric budgets.
- Keyword ranking.
- Category ranking boost.
- Price filtering and `over_price_cap`.
- Shipping filtering and `ship_to_unavailable`.
- Top-K behavior without changing `total_candidates` semantics.
- Empty results for unknown queries.

## Validation Result

All chapter tests pass: `13 passed`.

The search capability now runs independently of AgentScope, an LLM service, and the network. The Application depends only on the `ProductRepository` port defined by the Domain.

## Next Chapter

The next chapter wraps `CatalogSearchUseCase` in an AgentScope `FunctionTool` and registers it with the MainAgent `Toolkit`, creating the first complete ReAct tool-execution loop:

```text
User request → model selects tool → Python use case → tool result → final model response
```
