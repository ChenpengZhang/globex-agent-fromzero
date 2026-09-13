import type {
  ConversationHistoryResponse,
  ConversationTurnRecord,
  AsyncSubmitIntentResponse,
  SubmitIntentRequest,
  SubmitIntentResponse,
  TaskState,
  TaskStatusResponse,
} from "./types";


async function errorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json() as { detail?: unknown };

    if (typeof body.detail === "string") {
      return body.detail;
    }

    return JSON.stringify(body.detail ?? body);
  } catch {
    return response.statusText || "未知错误";
  }
}

export async function submitIntent(
  request: SubmitIntentRequest,
): Promise<SubmitIntentResponse> {
  const response = await fetch("/commerce/intents", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(
      `请求失败 (${response.status})：${await errorDetail(response)}`,
    );
  }

  const result = await response.json() as Partial<SubmitIntentResponse>;

  if (
    typeof result.shopping_session_id !== "string"
    || typeof result.final_text !== "string"
  ) {
    throw new Error("服务端返回了无法识别的响应格式");
  }

  return result as SubmitIntentResponse;
}

const TASK_STATES = new Set<TaskState>([
  "queued",
  "running",
  "retrying",
  "done",
  "failed",
]);

export async function submitIntentAsync(
  request: SubmitIntentRequest,
): Promise<AsyncSubmitIntentResponse> {
  const response = await fetch("/commerce/intents/async", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(
      `任务提交失败 (${response.status})：${await errorDetail(response)}`,
    );
  }

  const result = await response.json() as Partial<AsyncSubmitIntentResponse>;

  if (
    typeof result.shopping_session_id !== "string"
    || typeof result.task_id !== "string"
    || typeof result.state !== "string"
    || !TASK_STATES.has(result.state as TaskState)
  ) {
    throw new Error("服务端返回了无法识别的任务信息");
  }

  return result as AsyncSubmitIntentResponse;
}

export async function getTaskStatus(
  taskId: string,
  buyerId: string,
): Promise<TaskStatusResponse> {
  const query = new URLSearchParams({ buyer_id: buyerId });
  const response = await fetch(
    `/commerce/tasks/${encodeURIComponent(taskId)}?${query}`,
  );

  if (!response.ok) {
    throw new Error(
      `任务状态读取失败 (${response.status})：${await errorDetail(response)}`,
    );
  }

  const result = await response.json() as Partial<TaskStatusResponse>;

  if (
    typeof result.task_id !== "string"
    || typeof result.shopping_session_id !== "string"
    || typeof result.state !== "string"
    || !TASK_STATES.has(result.state as TaskState)
    || typeof result.final_text !== "string"
    || typeof result.error !== "string"
    || typeof result.queue_position !== "number"
  ) {
    throw new Error("服务端返回了无法识别的任务状态");
  }

  return result as TaskStatusResponse;
}

export async function waitForTask(
  taskId: string,
  buyerId: string,
  timeoutMs = 180_000,
): Promise<TaskStatusResponse> {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const status = await getTaskStatus(taskId, buyerId);

    if (status.state === "done" || status.state === "failed") {
      return status;
    }

    await new Promise((resolve) => window.setTimeout(resolve, 500));
  }

  throw new Error("Agent 任务等待超时，请稍后重试");
}

function isConversationTurn(value: unknown): value is ConversationTurnRecord {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const turn = value as Partial<ConversationTurnRecord>;

  return (
    (turn.role === "buyer" || turn.role === "agent")
    && typeof turn.content === "string"
    && typeof turn.model === "string"
    && typeof turn.latency_ms === "number"
    && typeof turn.created_at === "string"
  );
}

export async function loadConversationHistory(
  sessionId: string,
  buyerId: string,
  limit = 50,
): Promise<ConversationHistoryResponse | null> {
  const query = new URLSearchParams({
    buyer_id: buyerId,
    limit: String(limit),
  });
  const response = await fetch(
    `/commerce/sessions/${encodeURIComponent(sessionId)}/history?${query}`,
  );

  if (response.status === 404) {
    return null;
  }

  if (!response.ok) {
    throw new Error(
      `历史记录读取失败 (${response.status})：${await errorDetail(response)}`,
    );
  }

  const result = await response.json() as Partial<ConversationHistoryResponse>;

  if (
    typeof result.session_id !== "string"
    || !Array.isArray(result.turns)
    || !result.turns.every(isConversationTurn)
  ) {
    throw new Error("服务端返回了无法识别的历史记录格式");
  }

  return result as ConversationHistoryResponse;
}
