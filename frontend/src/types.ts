export interface SubmitIntentRequest {
  shopping_session_id: string;
  buyer_id: string;
  locale: string;
  currency: string;
  raw_query: string;
}

export interface SubmitIntentResponse {
  shopping_session_id: string;
  final_text: string;
}

export interface ConversationTurnRecord {
  role: "buyer" | "agent";
  content: string;
  model: string;
  latency_ms: number;
  created_at: string;
}

export interface ConversationHistoryResponse {
  session_id: string;
  turns: ConversationTurnRecord[];
}

export type ConnectionState =
  | "connecting"
  | "connected"
  | "disconnected";

export interface ChatTurn {
  id: string;
  role: "buyer" | "agent";
  text: string;
  tone?: "normal" | "error";
}

export interface ProductSku {
  sku_id: string;
  spec: string;
  price_major: number;
  currency: string;
  stock: number;
}

export interface ProductCard {
  product_id: string;
  title: string;
  brand: string;
  category: string;
  origin_country: string;
  ships_to: string[];
  skus: ProductSku[];
  score: number;
}

export interface MoneyView {
  amount_major: string;
  currency: string;
}

export interface OrderView {
  order_id: string;
  status: string;
  total_amount: MoneyView;
  lines: Array<{
    sku_id: string;
    title: string;
    quantity: number;
    subtotal: MoneyView;
  }>;
}

interface TradeEventBase {
  shopping_session_id: string;
  occurred_at: string;
}

export interface TokenDeltaEvent extends TradeEventBase {
  type: "token.delta";
  payload: {
    agent_name: string;
    token: string;
  };
}

export interface FinalResultEvent extends TradeEventBase {
  type: "final.result";
  payload: {
    text: string;
  };
}

export interface ErrorEvent extends TradeEventBase {
  type: "error";
  payload: {
    message: string;
  };
}

export interface ToolInvokeEvent extends TradeEventBase {
  type: "tool.invoke";
  payload: Record<string, unknown>;
}

export interface ToolResultEvent extends TradeEventBase {
  type: "tool.result";
  payload: {
    tool?: string;
    tool_name?: string;
    hits?: ProductCard[];
    order?: OrderView;
    error?: string;
    [key: string]: unknown;
  };
}

export interface AgentDispatchEvent extends TradeEventBase {
  type: "agent.dispatch";
  payload: Record<string, unknown>;
}

export type TradeEvent =
  | TokenDeltaEvent
  | FinalResultEvent
  | ErrorEvent
  | ToolInvokeEvent
  | ToolResultEvent
  | AgentDispatchEvent;

const EVENT_TYPES = new Set<TradeEvent["type"]>([
  "agent.dispatch",
  "tool.invoke",
  "tool.result",
  "token.delta",
  "final.result",
  "error",
]);

export function isTradeEvent(value: unknown): value is TradeEvent {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const candidate = value as Record<string, unknown>;

  return (
    typeof candidate.shopping_session_id === "string"
    && typeof candidate.type === "string"
    && EVENT_TYPES.has(candidate.type as TradeEvent["type"])
    && typeof candidate.payload === "object"
    && candidate.payload !== null
    && typeof candidate.occurred_at === "string"
  );
}
