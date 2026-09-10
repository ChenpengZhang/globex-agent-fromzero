import type {
  SubmitIntentRequest,
  SubmitIntentResponse,
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
