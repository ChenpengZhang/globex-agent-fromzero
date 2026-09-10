const BUYER_STORAGE_KEY = "globex.buyer-id";
const SESSION_STORAGE_KEY = "globex.session-id";

function createId(prefix: string): string {
  const randomPart = (
    typeof crypto.randomUUID === "function"
      ? crypto.randomUUID().slice(0, 8)
      : Math.random().toString(36).slice(2, 10)
  );

  return `${prefix}-${randomPart}`;
}

function loadOrCreate(key: string, prefix: string): string {
  const existing = window.localStorage.getItem(key);

  if (existing) {
    return existing;
  }

  const created = createId(prefix);
  window.localStorage.setItem(key, created);
  return created;
}

export function loadBuyerId(): string {
  return loadOrCreate(BUYER_STORAGE_KEY, "buyer");
}

export function loadSessionId(): string {
  return loadOrCreate(SESSION_STORAGE_KEY, "web");
}

export function replaceSessionId(): string {
  const created = createId("web");
  window.localStorage.setItem(SESSION_STORAGE_KEY, created);
  return created;
}

export function createTurnId(): string {
  return createId("turn");
}
