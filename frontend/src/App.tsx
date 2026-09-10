import {
  type FormEvent,
  type KeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";

import { submitIntent } from "./api";
import EventTimeline from "./components/EventTimeline";
import OrderCard from "./components/OrderCard";
import ProductCards from "./components/ProductCards";
import { connectEventStream } from "./eventStream";
import {
  createTurnId,
  loadBuyerId,
  loadSessionId,
  replaceSessionId,
} from "./session";
import type {
  ChatTurn,
  ConnectionState,
  TradeEvent,
} from "./types";


const STARTERS = [
  "推荐一个适合出差的轻量背包",
  "我想看看能寄到中国的旅行用品",
  "帮我查询刚才创建的订单",
];

function appendFinalTurn(turns: ChatTurn[], text: string): ChatTurn[] {
  const last = turns[turns.length - 1];

  if (last?.role === "agent" && last.text === text) {
    return turns;
  }

  return [
    ...turns,
    {
      id: createTurnId(),
      role: "agent",
      text,
    },
  ];
}

export default function App() {
  const [sessionId, setSessionId] = useState(loadSessionId);
  const [buyerId] = useState(loadBuyerId);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [events, setEvents] = useState<TradeEvent[]>([]);
  const [streamingText, setStreamingText] = useState("");
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setConnection("connecting");

    return connectEventStream(sessionId, {
      onOpen: () => {
        setConnection("connected");
      },
      onClose: () => {
        setConnection("disconnected");
      },
      onError: () => {
        setConnection("disconnected");
      },
      onEvent: (event) => {
        if (event.type === "token.delta") {
          setStreamingText((current) => current + event.payload.token);
          return;
        }

        setEvents((current) => [...current.slice(-99), event]);

        if (event.type === "final.result") {
          setStreamingText("");
          setTurns((current) => appendFinalTurn(current, event.payload.text));
          setBusy(false);
        }

        if (event.type === "error") {
          setNotice(event.payload.message);
          setBusy(false);
        }
      },
    });
  }, [sessionId]);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "end",
    });
  }, [turns, streamingText, busy]);

  async function send(queryOverride?: string) {
    const query = (queryOverride ?? input).trim();

    if (!query || busy) {
      return;
    }

    setInput("");
    setNotice(null);
    setBusy(true);
    setStreamingText("");
    setTurns((current) => [
      ...current,
      {
        id: createTurnId(),
        role: "buyer",
        text: query,
      },
    ]);

    try {
      const result = await submitIntent({
        shopping_session_id: sessionId,
        buyer_id: buyerId,
        locale: "zh-CN",
        currency: "CNY",
        raw_query: query,
      });

      setStreamingText("");
      setTurns((current) => appendFinalTurn(current, result.final_text));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setNotice(message);
      setTurns((current) => [
        ...current,
        {
          id: createTurnId(),
          role: "agent",
          text: message,
          tone: "error",
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void send();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void send();
    }
  }

  function startNewConversation() {
    if (busy) {
      return;
    }

    setSessionId(replaceSessionId());
    setTurns([]);
    setEvents([]);
    setStreamingText("");
    setNotice(null);
  }

  const connectionLabel = {
    connecting: "正在连接事件流",
    connected: "事件流已连接",
    disconnected: "事件流正在重连",
  }[connection];

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Globex 首页">
          <span className="brand-mark" aria-hidden="true">G</span>
          <span>
            <strong>Globex</strong>
            <small>Cross-border commerce agent</small>
          </span>
        </a>

        <div className="topbar-actions">
          <span className={`connection connection-${connection}`}>
            <span className="connection-dot" aria-hidden="true" />
            {connectionLabel}
          </span>
          <button
            className="secondary-button"
            disabled={busy}
            onClick={startNewConversation}
            type="button"
          >
            新对话
          </button>
        </div>
      </header>

      <main className="workspace">
        <section className="chat-panel" aria-label="购物对话">
          <div className="chat-heading">
            <div>
              <p className="eyebrow">SHOPPING SESSION</p>
              <h1>把购买需求交给我</h1>
            </div>
            <div className="identity">
              <span title={buyerId}>买家 {buyerId.slice(-8)}</span>
              <span title={sessionId}>会话 {sessionId.slice(-8)}</span>
            </div>
          </div>

          <div className="transcript" aria-live="polite">
            {turns.length === 0 && !streamingText ? (
              <div className="welcome">
                <span className="welcome-icon" aria-hidden="true">✦</span>
                <h2>你好，我是 Globex</h2>
                <p>
                  我可以帮你查找跨境商品、比较候选，并在确认后处理订单。
                </p>
                <div className="starter-list">
                  {STARTERS.map((starter) => (
                    <button
                      disabled={busy}
                      key={starter}
                      onClick={() => void send(starter)}
                      type="button"
                    >
                      {starter}
                      <span aria-hidden="true">→</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              turns.map((turn) => (
                <article
                  className={`message message-${turn.role} ${turn.tone === "error" ? "message-error" : ""}`}
                  key={turn.id}
                >
                  <div className="message-author">
                    {turn.role === "buyer" ? "你" : "G"}
                  </div>
                  <div className="message-body">
                    <span>{turn.role === "buyer" ? "你" : "Globex"}</span>
                    <p>{turn.text}</p>
                  </div>
                </article>
              ))
            )}

            {streamingText && (
              <article className="message message-agent message-streaming">
                <div className="message-author">G</div>
                <div className="message-body">
                  <span>Globex</span>
                  <p>{streamingText}<i className="cursor" aria-hidden="true" /></p>
                </div>
              </article>
            )}

            {busy && !streamingText && (
              <div className="thinking" role="status">
                <span /><span /><span />
                Globex 正在处理你的需求
              </div>
            )}

            <div ref={transcriptEndRef} />
          </div>

          <ProductCards events={events} />
          <OrderCard events={events} />

          {notice && (
            <div className="notice" role="alert">
              <span>!</span>
              <p>{notice}</p>
              <button onClick={() => setNotice(null)} type="button">关闭</button>
            </div>
          )}

          <form className="composer" onSubmit={handleSubmit}>
            <label className="sr-only" htmlFor="shopping-query">
              输入购物需求
            </label>
            <textarea
              id="shopping-query"
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="描述你想购买的商品、预算和配送目的地……"
              rows={3}
              value={input}
            />
            <div className="composer-footer">
              <span>Enter 发送 · Shift + Enter 换行</span>
              <button disabled={busy || !input.trim()} type="submit">
                {busy ? "处理中" : "发送需求"}
                <span aria-hidden="true">↑</span>
              </button>
            </div>
          </form>
        </section>

        <EventTimeline events={events} />
      </main>
    </div>
  );
}
