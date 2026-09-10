import {
  isTradeEvent,
  type TradeEvent,
} from "./types";


export interface EventStreamHandlers {
  onOpen?: () => void;
  onEvent: (event: TradeEvent) => void;
  onClose?: () => void;
  onError?: (error: unknown) => void;
}

const RETRY_DELAY_MS = 1500;

export function connectEventStream(
  shoppingSessionId: string,
  handlers: EventStreamHandlers,
): () => void {
  let socket: WebSocket | null = null;
  let retryTimer: number | undefined;
  let stopped = false;

  const connect = () => {
    if (stopped) {
      return;
    }

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${window.location.host}/commerce/events`;

    socket = new WebSocket(url);

    socket.addEventListener("open", () => {
      if (stopped) {
        socket?.close();
        return;
      }

      socket?.send(JSON.stringify({
        shopping_session_id: shoppingSessionId,
      }));
      handlers.onOpen?.();
    });

    socket.addEventListener("message", (message) => {
      try {
        const parsed = JSON.parse(String(message.data)) as unknown;

        if (!isTradeEvent(parsed)) {
          throw new Error("收到无法识别的事件格式");
        }

        handlers.onEvent(parsed);
      } catch (error) {
        handlers.onError?.(error);
      }
    });

    socket.addEventListener("close", () => {
      handlers.onClose?.();

      if (!stopped) {
        retryTimer = window.setTimeout(connect, RETRY_DELAY_MS);
      }
    });

    socket.addEventListener("error", (error) => {
      handlers.onError?.(error);
    });
  };

  connect();

  return () => {
    stopped = true;

    if (retryTimer !== undefined) {
      window.clearTimeout(retryTimer);
    }

    socket?.close();
  };
}
