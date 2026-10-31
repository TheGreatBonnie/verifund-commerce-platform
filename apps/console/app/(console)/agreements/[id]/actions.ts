"use server";

const CONTROL_PLANE =
  process.env.VERIFUND_CONTROL_PLANE_URL ?? "http://127.0.0.1:9300";

function actorHeaders() {
  return {
    "X-Actor-Id": "demo-buyer",
    "X-Actor-Type": "buyer",
  };
}

export async function approveAgreement(
  id: string,
  version: number,
  hash: string,
  note: string,
  idempotencyKey: string,
) {
  // issue token server-side
  const tokenRes = await fetch(
    `${CONTROL_PLANE}/agreements/${encodeURIComponent(id)}/approval-token`,
    {
      method: "POST",
      headers: { ...actorHeaders(), "Idempotency-Key": idempotencyKey },
      cache: "no-store",
    },
  );
  if (!tokenRes.ok) {
    return { error: "token_failed", decisionRecorded: false };
  }
  const tokenBody = (await tokenRes.json()) as { token: string };
  const decisionRes = await fetch(
    `${CONTROL_PLANE}/agreements/${encodeURIComponent(id)}/buyer-decision`,
    {
      method: "POST",
      headers: {
        ...actorHeaders(),
        "content-type": "application/json",
        "Idempotency-Key": idempotencyKey,
        "X-Approval-Token": tokenBody.token,
      },
      body: JSON.stringify({
        agreement_version: version,
        agreement_hash: hash,
        decision: "APPROVE",
        note,
        idempotency_key: idempotencyKey,
      }),
      cache: "no-store",
    },
  );
  if (!decisionRes.ok) {
    return { error: "decision_failed", decisionRecorded: false };
  }
  return { decisionRecorded: true };
}

export async function rejectAgreement(
  id: string,
  version: number,
  hash: string,
  note: string,
  idempotencyKey: string,
) {
  const tokenRes = await fetch(
    `${CONTROL_PLANE}/agreements/${encodeURIComponent(id)}/approval-token`,
    {
      method: "POST",
      headers: { ...actorHeaders(), "Idempotency-Key": idempotencyKey },
      cache: "no-store",
    },
  );
  if (!tokenRes.ok) return { error: "token_failed", decisionRecorded: false };
  const tokenBody = (await tokenRes.json()) as { token: string };
  const decisionRes = await fetch(
    `${CONTROL_PLANE}/agreements/${encodeURIComponent(id)}/buyer-decision`,
    {
      method: "POST",
      headers: {
        ...actorHeaders(),
        "content-type": "application/json",
        "Idempotency-Key": idempotencyKey,
        "X-Approval-Token": tokenBody.token,
      },
      body: JSON.stringify({
        agreement_version: version,
        agreement_hash: hash,
        decision: "REJECT",
        note,
        idempotency_key: idempotencyKey,
      }),
      cache: "no-store",
    },
  );
  if (!decisionRes.ok) return { error: "decision_failed", decisionRecorded: false };
  return { decisionRecorded: true };
}

export async function requestChangesAgreement(
  id: string,
  version: number,
  hash: string,
  note: string,
  idempotencyKey: string,
) {
  const tokenRes = await fetch(
    `${CONTROL_PLANE}/agreements/${encodeURIComponent(id)}/approval-token`,
    {
      method: "POST",
      headers: { ...actorHeaders(), "Idempotency-Key": idempotencyKey },
      cache: "no-store",
    },
  );
  if (!tokenRes.ok) return { error: "token_failed", decisionRecorded: false };
  const tokenBody = (await tokenRes.json()) as { token: string };
  const decisionRes = await fetch(
    `${CONTROL_PLANE}/agreements/${encodeURIComponent(id)}/buyer-decision`,
    {
      method: "POST",
      headers: {
        ...actorHeaders(),
        "content-type": "application/json",
        "Idempotency-Key": idempotencyKey,
        "X-Approval-Token": tokenBody.token,
      },
      body: JSON.stringify({
        agreement_version: version,
        agreement_hash: hash,
        decision: "REQUEST_CHANGES",
        note,
        idempotency_key: idempotencyKey,
      }),
      cache: "no-store",
    },
  );
  if (!decisionRes.ok) return { error: "decision_failed", decisionRecorded: false };
  return { decisionRecorded: true };
}
