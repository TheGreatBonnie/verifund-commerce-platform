export function BuyerConfirmDialog({
  title,
  body,
  confirmLabel,
  onConfirm,
  onCancel,
  busy = false,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
}) {
  return (
    <div className="mm-buyer-confirm-backdrop">
      <div
        className="mm-panel mm-buyer-confirm"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <h2>{title}</h2>
        <p>{body}</p>
        <div className="mm-buyer-inline-actions">
          <button type="button" onClick={onConfirm} disabled={busy}>
            {confirmLabel}
          </button>
          <button type="button" onClick={onCancel} disabled={busy} autoFocus>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
