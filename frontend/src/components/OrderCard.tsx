import type {
  OrderView,
  TradeEvent,
} from "../types";


function latestOrder(events: TradeEvent[]): OrderView | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];

    if (event.type === "tool.result" && event.payload.order) {
      return event.payload.order;
    }
  }

  return null;
}

export default function OrderCard({ events }: { events: TradeEvent[] }) {
  const order = latestOrder(events);

  if (order === null) {
    return null;
  }

  return (
    <section className="order-card" aria-label="最新订单">
      <div className="order-card-heading">
        <div>
          <p className="eyebrow">LATEST ORDER</p>
          <h2>{order.order_id}</h2>
        </div>
        <span className={`order-status status-${order.status.toLowerCase()}`}>
          {order.status}
        </span>
      </div>

      <ul className="order-lines">
        {order.lines.map((line) => (
          <li key={`${line.sku_id}-${line.quantity}`}>
            <span>{line.title} × {line.quantity}</span>
            <strong>
              {line.subtotal.amount_major} {line.subtotal.currency}
            </strong>
          </li>
        ))}
      </ul>

      <div className="order-total">
        <span>订单总额</span>
        <strong>
          {order.total_amount.amount_major} {order.total_amount.currency}
        </strong>
      </div>
    </section>
  );
}
