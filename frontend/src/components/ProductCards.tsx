import type {
  ProductCard,
  TradeEvent,
} from "../types";


function latestProducts(events: TradeEvent[]): ProductCard[] {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];

    if (event.type === "tool.result" && Array.isArray(event.payload.hits)) {
      return event.payload.hits;
    }
  }

  return [];
}

export default function ProductCards({ events }: { events: TradeEvent[] }) {
  const products = latestProducts(events);

  if (products.length === 0) {
    return null;
  }

  return (
    <section className="result-section" aria-label="商品候选">
      <div className="result-heading">
        <span>匹配商品</span>
        <span>{products.length} 项</span>
      </div>

      <div className="product-grid">
        {products.map((product) => {
          const primarySku = product.skus[0];

          return (
            <article className="product-card" key={product.product_id}>
              <div className="product-card-top">
                <span className="product-category">{product.category}</span>
                <span className="product-score">
                  相关度 {product.score.toFixed(2)}
                </span>
              </div>
              <h3>{product.title}</h3>
              <p className="product-origin">
                {product.brand} · {product.origin_country}
              </p>

              {primarySku && (
                <div className="product-price">
                  <strong>{primarySku.price_major}</strong>
                  <span>{primarySku.currency}</span>
                </div>
              )}

              <div className="sku-list">
                {product.skus.map((sku) => (
                  <span className="sku-pill" key={sku.sku_id}>
                    {sku.spec} · 库存 {sku.stock}
                  </span>
                ))}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
