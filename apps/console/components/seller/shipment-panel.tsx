"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/format";
import type { ShipmentState } from "@/lib/seller-types";

function statusLabel(status?: string | null): string {
  if (!status) return "unknown";
  return status.replaceAll("_", " ");
}

export function ShipmentPanel({
  transactionId,
  initialShipment,
  canRegister,
}: {
  transactionId: string;
  initialShipment: ShipmentState | null;
  canRegister: boolean;
}) {
  const router = useRouter();
  const [shipmentState, setShipmentState] = useState<ShipmentState | null>(initialShipment);
  const [carrierKey, setCarrierKey] = useState("mock");
  const [trackingNumber, setTrackingNumber] = useState("");
  const [serviceLevel, setServiceLevel] = useState("");
  const [scenario, setScenario] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const shipment = shipmentState?.shipment;
  const events = shipmentState?.events ?? [];
  const delivery = shipmentState?.delivery_confirmation;

  const register = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = {
        carrier_key: carrierKey || "mock",
        tracking_number: trackingNumber.trim(),
      };
      if (serviceLevel.trim()) payload.service_level = serviceLevel.trim();
      if (scenario.trim()) payload.scenario = scenario.trim();
      const response = await fetch(
        `/api/seller/transactions/${encodeURIComponent(transactionId)}/shipment`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(payload),
        },
      );
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(body?.error?.message || body?.detail || `Failed (${response.status})`);
      }
      setShipmentState(body as ShipmentState);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to register shipment");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="mm-panel" aria-label="Shipment and delivery">
      <div className="mm-panel-head">
        <div>
          <p className="mm-kicker">Packaging & delivery</p>
          <h2>Shipment</h2>
        </div>
        {shipment ? <span className="mm-seller-chip">{statusLabel(shipment.status)}</span> : null}
      </div>

      {!shipment && canRegister ? (
        <form className="mm-seller-upload-form" onSubmit={register}>
          <div className="mm-seller-field-grid">
            <label className="mm-seller-field">
              <span>Carrier</span>
              <input value={carrierKey} onChange={(e) => setCarrierKey(e.target.value)} placeholder="mock / ups / fedex" required />
            </label>
            <label className="mm-seller-field">
              <span>Tracking number</span>
              <input value={trackingNumber} onChange={(e) => setTrackingNumber(e.target.value)} placeholder="Tracking number" required />
            </label>
            <label className="mm-seller-field">
              <span>Service level (optional)</span>
              <input value={serviceLevel} onChange={(e) => setServiceLevel(e.target.value)} placeholder="ground / express" />
            </label>
            <label className="mm-seller-field">
              <span>Scenario (sandbox/test)</span>
              <input value={scenario} onChange={(e) => setScenario(e.target.value)} placeholder="happy_path / never_delivers / ..." />
            </label>
          </div>
          <div className="mm-seller-upload-actions">
            <Button type="submit" loading={loading}>Register shipment</Button>
          </div>
        </form>
      ) : shipment ? (
        <div className="mm-seller-facts">
          <div className="mm-seller-fact"><dt>Carrier</dt><dd>{shipment.carrier_key ?? "—"}</dd></div>
          <div className="mm-seller-fact"><dt>Tracking</dt><dd className="mm-mono-note">{shipment.tracking_number ?? "—"}</dd></div>
          <div className="mm-seller-fact"><dt>Status</dt><dd>{statusLabel(shipment.status)}</dd></div>
          {shipment.service_level ? <div className="mm-seller-fact"><dt>Service</dt><dd>{shipment.service_level}</dd></div> : null}
          {shipment.updated_at ? <div className="mm-seller-fact"><dt>Updated</dt><dd>{formatDateTime(shipment.updated_at)}</dd></div> : null}
        </div>
      ) : (
        <p className="mm-empty">No shipment registered yet.</p>
      )}

      {events.length ? (
        <div className="mm-seller-checks" aria-label="Carrier events">
          <span className="mm-kicker">Carrier timeline</span>
          <ul className="mm-seller-submissions">
            {events.map((ev, idx) => (
              <li key={`${ev.provider_event_id ?? idx}`}>
                <div className="mm-seller-submission-main">
                  <span className="mm-seller-submission-type">{statusLabel(ev.normalized_status)}</span>
                  <span className="mm-seller-submission-meta">
                    {ev.event_at ? formatDateTime(ev.event_at) : "—"}
                    {typeof ev.weight_g === "number" ? ` · ${ev.weight_g}g` : ""}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {delivery ? (
        <p className="mm-mono-note">
          Delivery confirmed{delivery.delivered_at ? ` at ${formatDateTime(delivery.delivered_at)}` : ""}
          {delivery.pod_reference ? ` · POD ${delivery.pod_reference}` : ""}.
        </p>
      ) : null}

      {error ? <Alert message={error} /> : null}
    </section>
  );
}
