export function mapActionError(error: unknown): string {
  const err = error as { status?: number; message?: string; body?: any } | null;
  const message = typeof err?.message === "string" ? err.message : "";

  if (err?.status === 409) {
    return `This action is no longer available because the transaction state changed.${message ? ` ${message}` : ""}`;
  }
  if (err?.status === 422) {
    return `The request was rejected.${message ? ` ${message}` : " Check the entered details."}`;
  }
  if (err?.status === 415) {
    return "That file type is not supported. Upload a PDF, PNG or JPEG.";
  }
  if (err?.status === 401 || err?.status === 403) {
    return "You do not have permission to perform this action.";
  }

  const code = err?.body?.error?.code ?? err?.body?.code;
  const prefix = typeof code === "string" && code ? `${code}: ` : "";
  return `${prefix}${message}` || "Action failed. Please try again.";
}
