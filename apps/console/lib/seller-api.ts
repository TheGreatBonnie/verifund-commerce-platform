import { cookies } from "next/headers";
import type { EvidenceItem, EvidenceReceipt } from "./seller-types";

const CONTROL_PLANE =
  process.env.VERIFUND_CONTROL_PLANE_URL ?? "http://127.0.0.1:9300";
const TIMEOUT_MS = 15_000;

/**
 * Seller sessions are kept server-side in an HttpOnly cookie. The browser
 * never receives the seller bearer token; server components and route
 * handlers attach it to control-plane requests.
 */
export const SELLER_COOKIE = "verifund_seller_sessions";

export class SellerApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "SellerApiError";
    this.status = status;
    this.code = code;
  }
}

type StoredSellerToken = {
  token: string;
  transaction_id: string;
  seller_id: string | null;
  expires_at: string | null;
};

type SellerTokenStore = {
  primary: string | null;
  tokens: Record<string, StoredSellerToken>;
};

export type SellerSession = {
  token: string;
  transactionId: string;
  sellerId: string | null;
  expiresAt: Date | null;
};

export type SellerClaims = {
  transactionId: string | null;
  sellerId: string | null;
  expiresAt: Date | null;
};

export type SellerResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: string; status: number };

export type InvitationExchange = {
  token: string;
  expires_at: string;
  allowed_actions: string[];
};

function emptyStore(): SellerTokenStore {
  return { primary: null, tokens: {} };
}

function decodeStore(value?: string): SellerTokenStore {
  if (!value) return emptyStore();
  try {
    const parsed = JSON.parse(
      Buffer.from(value, "base64url").toString("utf8"),
    ) as Partial<SellerTokenStore>;
    if (!parsed || typeof parsed !== "object" || !parsed.tokens) {
      return emptyStore();
    }
    return {
      primary: typeof parsed.primary === "string" ? parsed.primary : null,
      tokens: parsed.tokens,
    };
  } catch {
    return emptyStore();
  }
}

function encodeStore(store: SellerTokenStore): string {
  return Buffer.from(JSON.stringify(store), "utf8").toString("base64url");
}

function cookieOptions(expiresAt?: Date | null) {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
    path: "/",
    ...(expiresAt ? { expires: expiresAt } : {}),
  };
}

export function decodeSellerToken(token: string): SellerClaims {
  try {
    const parts = token.split(".");
    const payload = parts.length >= 3 ? parts[1] : parts[0];
    const claims = JSON.parse(
      Buffer.from(payload, "base64url").toString("utf8"),
    ) as Record<string, unknown>;
    const expiresAt =
      typeof claims.exp === "number" ? new Date(claims.exp * 1000) : null;
    return {
      transactionId: typeof claims.txn === "string" ? claims.txn : null,
      sellerId: typeof claims.seller_id === "string" ? claims.seller_id : null,
      expiresAt,
    };
  } catch {
    return { transactionId: null, sellerId: null, expiresAt: null };
  }
}

async function readTokenStore(): Promise<SellerTokenStore> {
  const jar = await cookies();
  return decodeStore(jar.get(SELLER_COOKIE)?.value);
}

function validSession(entry: StoredSellerToken): SellerSession | null {
  const expiresAt = entry.expires_at ? new Date(entry.expires_at) : null;
  if (expiresAt && expiresAt.getTime() <= Date.now()) return null;
  return {
    token: entry.token,
    transactionId: entry.transaction_id,
    sellerId: entry.seller_id,
    expiresAt,
  };
}

/**
 * Read the seller session for a transaction (detail/upload pages) or the
 * primary session (seller-wide list pages).
 */
export async function readSellerSession(
  transactionId?: string,
): Promise<SellerSession | null> {
  const store = await readTokenStore();
  if (transactionId) {
    const entry = store.tokens[transactionId];
    return entry ? validSession(entry) : null;
  }
  if (store.primary && store.tokens[store.primary]) {
    const primary = validSession(store.tokens[store.primary]);
    if (primary) return primary;
  }
  for (const entry of Object.values(store.tokens)) {
    const session = validSession(entry);
    if (session) return session;
  }
  return null;
}

export async function readAllSellerSessions(): Promise<SellerSession[]> {
  const store = await readTokenStore();
  return Object.values(store.tokens)
    .map(validSession)
    .filter((session): session is SellerSession => session !== null);
}

async function sellerToken(transactionId?: string): Promise<string> {
  const session = await readSellerSession(transactionId);
  if (!session) {
    throw new SellerApiError(
      transactionId
        ? "No seller session is available for this order"
        : "Seller access is required",
      401,
    );
  }
  return session.token;
}

async function failure(response: Response): Promise<SellerApiError> {
  let message = `Seller API responded ${response.status}`;
  let code: string | undefined;
  try {
    const body = (await response.json()) as {
      error?: { message?: string; code?: string };
      detail?: string;
    };
    message = body.error?.message ?? body.detail ?? message;
    code = body.error?.code;
  } catch {
    // Keep the status-based message when the body is not JSON.
  }
  return new SellerApiError(message, response.status, code);
}

export async function sellerRequest(
  path: string,
  init: RequestInit = {},
  transactionId?: string,
): Promise<Response> {
  const token = await sellerToken(transactionId);
  const headers = new Headers(init.headers);
  headers.set("authorization", `Bearer ${token}`);
  try {
    return await fetch(`${CONTROL_PLANE}${path}`, {
      ...init,
      cache: "no-store",
      headers,
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch {
    throw new SellerApiError("Control plane is unavailable", 503);
  }
}

export async function sellerJson<T>(
  path: string,
  init: RequestInit = {},
  transactionId?: string,
): Promise<T> {
  const response = await sellerRequest(path, init, transactionId);
  if (!response.ok) throw await failure(response);
  return (await response.json()) as T;
}

export async function loadSeller<T>(
  path: string,
  transactionId?: string,
): Promise<SellerResult<T>> {
  try {
    return { ok: true, data: await sellerJson<T>(path, {}, transactionId) };
  } catch (error) {
    if (error instanceof SellerApiError) {
      return { ok: false, error: error.message, status: error.status };
    }
    return {
      ok: false,
      error: error instanceof Error ? error.message : "Seller API is unavailable",
      status: 503,
    };
  }
}

export async function exchangeInvitation(
  token: string,
): Promise<InvitationExchange> {
  let response: Response;
  try {
    response = await fetch(
      `${CONTROL_PLANE}/fulfillment/access/${encodeURIComponent(token)}`,
      {
        method: "POST",
        cache: "no-store",
        signal: AbortSignal.timeout(TIMEOUT_MS),
      },
    );
  } catch {
    throw new SellerApiError("Control plane is unavailable", 503);
  }
  if (!response.ok) throw await failure(response);
  return (await response.json()) as InvitationExchange;
}

/**
 * Persist an exchanged seller token under its transaction. Called only from a
 * Server Action or route handler, where cookies are writable.
 */
export async function saveSellerToken(token: string): Promise<string> {
  const claims = decodeSellerToken(token);
  if (!claims.transactionId) {
    throw new SellerApiError(
      "The seller token is not bound to a transaction",
      502,
    );
  }
  const store = await readTokenStore();
  store.tokens[claims.transactionId] = {
    token,
    transaction_id: claims.transactionId,
    seller_id: claims.sellerId,
    expires_at: claims.expiresAt?.toISOString() ?? null,
  };
  store.primary = claims.transactionId;
  const jar = await cookies();
  jar.set(SELLER_COOKIE, encodeStore(store), cookieOptions(claims.expiresAt));
  return claims.transactionId;
}

export async function clearSellerTokens(): Promise<void> {
  const jar = await cookies();
  jar.delete(SELLER_COOKIE);
}

export async function uploadEvidence(
  transactionId: string,
  formData: FormData,
): Promise<EvidenceReceipt> {
  const response = await sellerRequest(
    `/seller/transactions/${encodeURIComponent(transactionId)}/evidence`,
    { method: "POST", body: formData },
    transactionId,
  );
  if (!response.ok) throw await failure(response);
  return (await response.json()) as EvidenceReceipt;
}

export async function uploadDisputeEvidence(
  transactionId: string,
  formData: FormData,
): Promise<EvidenceItem> {
  const response = await sellerRequest(
    `/seller/transactions/${encodeURIComponent(transactionId)}/dispute-evidence`,
    { method: "POST", body: formData },
    transactionId,
  );
  if (!response.ok) throw await failure(response);
  return (await response.json()) as EvidenceItem;
}
