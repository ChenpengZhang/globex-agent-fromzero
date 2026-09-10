import type { TradeEvent } from "../types";


const LABELS: Record<TradeEvent["type"], string> = {
  "agent.dispatch": "子 Agent 调度",
  "tool.invoke": "工具开始",
  "tool.result": "工具完成",
  "token.delta": "文本片段",
  "final.result": "回复完成",
  "error": "发生错误",
};

function eventSummary(event: TradeEvent): string {
  if (event.type === "final.result") {
    return event.payload.text.slice(0, 80);
  }

  if (event.type === "error") {
    return event.payload.message;
  }

  if (event.type === "tool.result") {
    const name = String(event.payload.tool_name ?? event.payload.tool ?? "工具");
    const hits = event.payload.hits;

    if (Array.isArray(hits)) {
      return `${name} 返回 ${hits.length} 个候选商品`;
    }

    if (event.payload.order) {
      return `${name} 返回订单 ${event.payload.order.order_id}`;
    }

    return event.payload.error
      ? `${name}：${event.payload.error}`
      : `${name} 已完成`;
  }

  if (event.type === "tool.invoke") {
    return String(
      event.payload.tool_name
      ?? event.payload.tool
      ?? "正在调用工具",
    );
  }

  if (event.type === "agent.dispatch") {
    return String(
      event.payload.agent_name
      ?? event.payload.agent
      ?? "正在派发任务",
    );
  }

  return "";
}

function eventTime(value: string): string {
  const timestamp = new Date(value);

  if (Number.isNaN(timestamp.getTime())) {
    return "--:--:--";
  }

  return timestamp.toLocaleTimeString("zh-CN", {
    hour12: false,
  });
}

interface EventTimelineProps {
  events: TradeEvent[];
}

export default function EventTimeline({ events }: EventTimelineProps) {
  return (
    <aside className="timeline" aria-label="Agent 事件时间线">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">LIVE TRACE</p>
          <h2>执行轨迹</h2>
        </div>
        <span className="event-count">{events.length}</span>
      </div>

      {events.length === 0 ? (
        <div className="timeline-empty">
          <span className="timeline-empty-icon" aria-hidden="true">◎</span>
          <p>发送购物需求后，这里会显示 Agent 的执行事件。</p>
        </div>
      ) : (
        <ol className="event-list">
          {events.map((event, index) => (
            <li
              className={`event-item event-${event.type.replace(".", "-")}`}
              key={`${event.occurred_at}-${index}`}
            >
              <span className="event-node" aria-hidden="true" />
              <div className="event-content">
                <div className="event-meta">
                  <span>{LABELS[event.type]}</span>
                  <time dateTime={event.occurred_at}>
                    {eventTime(event.occurred_at)}
                  </time>
                </div>
                <p>{eventSummary(event)}</p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </aside>
  );
}
