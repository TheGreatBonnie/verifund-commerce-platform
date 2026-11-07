import { controlPlaneForUser } from "@/lib/control-plane";

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

export type SellerResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: string; status: number };

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

export async function sellerJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await controlPlaneForUser(path, init);
  if (!response.ok) throw await failure(response);
  return (await response.json()) as T;
}

export async function loadSeller<T>(
  path: string,
  _transactionId?: string,
): Promise<SellerResult<T>> {
  try {
    return { ok: true, data: await sellerJson<T>(path) };
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

export async function clearSellerTokens(): Promise<void> {
  // Legacy cookie sessions removed for Clerk-based workspace access.
}

// Compatibility shims for migrated code paths. Prefer controlPlaneForUser directly.
export async function sellerRequest(
  path: string,
  init: RequestInit = {},
  _transactionId?: string,
): Promise<Response> {
  try {
    return await controlPlaneForUser(path, init);
  } catch (error) {
    if (error instanceof SellerApiError) throw error;
    throw new SellerApiError(
      error instanceof Error ? error.message : "Control plane is unavailable",
      503,
    );
  }
}

export async function uploadEvidence(
  transactionId: string,
  formData: FormData,
): Promise<unknown> {
  const response = await sellerRequest(
    `/seller/transactions/${encodeURIComponent(transactionId)}/evidence`,
    { method: "POST", body: formData },
  );
  if (!response.ok) throw await failure(response);
  return (await response.json()) as unknown;
}

export async function uploadDisputeEvidence(
  transactionId: string,
  formData: FormData,
): Promise<unknown> {
  const response = await sellerRequest(
    `/seller/transactions/${encodeURIComponent(transactionId)}/dispute-evidence`,
    { method: "POST", body: formData },
  );
  if (!response.ok) throw await failure(response);
  return (await response.json()) as unknown;
}

export type SellerSession = {
  token: string;
  transactionId: string;
  sellerId: string | null;
  expiresAt: Date | null;
};

export async function readSellerSession(
  _transactionId?: string,
): Promise<SellerSession | null> {
  return null;
}

export async function readAllSellerSessions(): Promise<SellerSession[]> {
  return [];
}

export async function exchangeInvitation(_token: string): Promise<never> {
  throw new SellerApiError(
    "Legacy seller invitation exchange is not used; seller access is managed via Clerk.",
    410,
  );
}

export async function saveSellerToken(_token: string): Promise<never> {
  throw new SellerApiError(
    "Legacy seller sessions are not used; seller access is managed via Clerk.",
    410,
  );
}

export function decodeSellerToken(_token: string): {
  transactionId: string | null;
  sellerId: string | null;
  expiresAt: Date | null;
} {
  return { transactionId: null, sellerId: null, expiresAt: null };
}

export const SELLER_COOKIE = "verifund_seller_sessions";
