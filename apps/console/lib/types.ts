export type OfferLineItem = {
  sku: string;
  name: string;
  quantity: number;
  unit_price_cents: number;
  list_unit_price_cents: number;
  warranty_addon_cents: number;
  attributes: Record<string, string>;
};

export type Offer = {
  offer_id: string;
  request_id: string;
  seller_id: string;
  seller_name: string;
  seller_rating: number;
  currency: string;
  line_items: OfferLineItem[];
  subtotal_cents: number;
  shipping_cents: number;
  total_cents: number;
  delivery_days: number;
  warranty_months: number;
  returns_days: number;
  valid_until: string;
  terms: {
    sustainability_certified: boolean;
    stock_confidence: number;
    split_shipment: boolean;
    notes?: string | null;
  };
  status: "proposed" | "final" | "accepted" | "rejected";
  round: number;
  rationale: string;
};

export type Negotiation = {
  seller_id: string;
  seller_name: string;
  task_id: string;
  status:
    | "open"
    | "final"
    | "accepted"
    | "rejected"
    | "cancelled"
    | "error"
    | string;
  rounds: Offer[];
  final_offer: Offer | null;
  error: string | null;
};

export type Award = {
  winner: Offer;
  score: number;
  alternatives: Offer[];
  scores: Record<string, number>;
  savings_cents: number;
  mandate_checks: string[];
};

export type Order = {
  order_id: string;
  offer_id: string;
  seller_id: string;
  status: string;
  quantity: number;
  total_cents: number;
  reserved_at: string;
  eta: string;
  tracking_number: string;
  line_items: OfferLineItem[];
  fulfillment: { carrier: string; status: string };
};

export type Mandate = {
  run_id?: string;
  buyer_id?: string;
  category?: string;
  product_hint?: string;
  quantity?: number;
  max_total_cents?: number;
  deadline_days?: number;
  min_warranty_months?: number;
  min_returns_days?: number;
  preferences?: { sustainability?: boolean; color?: string | null };
  approval_required?: boolean;
};

export type BuyerState = {
  run_id?: string;
  task_id?: string;
  status?: string;
  stage?: string;
  mandate?: Mandate | null;
  sellers?: Array<{
    seller_id: string;
    name: string;
    card_url: string;
    rating: number;
    sustainability_certified: boolean;
  }>;
  offers?: Offer[];
  negotiations?: Negotiation[];
  award?: Award | null;
  approval?: {
    approved?: boolean;
    approved_by?: string;
    note?: string;
  } | null;
  order?: Order | null;
  settlement?: SettlementProjection | null;
  settlement_receipt?: SettlementReceipt | null;
  error?: { code?: string; message?: string } | string | null;
  award_summary?: string;
  message?: string;
  trace?: Array<{
    type?: string;
    action?: string;
    rationale?: string;
    seller_id?: string | null;
    source?: string;
    fallback_used?: boolean;
  }>;
};

export type TraceEvent = {
  id: number;
  run_id: string;
  seq: number;
  created_at: string;
  direction: "inbound" | "outbound" | string;
  seller_id: string | null;
  method: string;
  task_id: string | null;
  context_id: string | null;
  payload: Record<string, unknown>;
  latency_ms: number | null;
};

export type RegistrySeller = {
  seller_id: string;
  name: string;
  card_url: string;
  categories: string[];
  card_hash: string;
  last_seen_at: string;
  healthy: boolean;
  last_error: string | null;
  card_json?: {
    name?: string;
    description?: string;
    version?: string;
    provider?: { organization?: string; url?: string };
    supportedInterfaces?: Array<{
      url?: string;
      protocolBinding?: string;
      protocolVersion?: string;
    }>;
    capabilities?: {
      streaming?: boolean;
      pushNotifications?: boolean;
      extensions?: Array<{ uri?: string; required?: boolean }>;
    };
    skills?: Array<{
      id?: string;
      name?: string;
      description?: string;
      tags?: string[];
      inputModes?: string[];
      outputModes?: string[];
    }>;
    defaultInputModes?: string[];
    defaultOutputModes?: string[];
    securitySchemes?: Record<string, unknown>;
  };
};

export type SellerDashboard = {
  seller_id: string;
  pricing: {
    product_name: string;
    sku: string;
    currency: string;
    list_unit_price_cents: number;
    base_warranty_months: number;
    warranty_addons_cents: Record<string, number>;
    returns_days: number;
    delivery_days: number;
    rating: number;
    sustainability_certified: boolean;
  };
  stock: {
    on_hand: number;
    incoming: number;
    incoming_days: number | null;
  };
  products: Array<{
    sku: string;
    product_name: string;
    category: string;
    description: string;
    list_unit_price_cents: number;
    currency: string;
    stock: { on_hand: number; incoming: number; incoming_days: number | null };
  }>;
  recent_offers: Array<{
    created_at: string;
    offer: {
      offer_id: string;
      status: string;
      currency: string;
      total_cents: number;
      line_items: Array<Pick<OfferLineItem, "quantity" | "name">>;
    };
  }>;
  recent_orders: Array<{
    created_at: string;
    order: {
      order_id: string;
      status: string;
      currency: string;
      quantity: number;
      total_cents: number;
      eta: string;
      fulfillment: { status: string };
    };
  }>;
  settlement?: Array<{
    transaction_id: string;
    seller_id: string;
    state: string;
    amount_cents?: number | null;
    currency?: string | null;
    deadlines?: { evidence?: string | null; inspection?: string | null };
    evidence?: SettlementProjection["evidence"];
    unavailable?: boolean;
  }>;
};

export type MarketplaceProduct = {
  id: string;
  sku: string;
  name: string;
  category: string;
  description: string;
  image_emoji: string;
  color: string;
  original_unit_price_cents: number | null;
  rating: number;
  reviews: string;
  tag: string;
  unit_price_cents: number;
  seller: string;
  offers: Array<{
    seller_id: string;
    seller_name: string;
    unit_price_cents: number;
    currency: string;
    available: boolean;
    on_hand: number;
    incoming: number;
  }>;
};

export type SettlementState =
  | "AWARDED"
  | "AGREED"
  | "FUNDING_PENDING"
  | "FUNDED"
  | "FULFILLMENT_PENDING"
  | "VERIFICATION_PENDING"
  | "RELEASE_PERMITTED"
  | "PAYOUT_PENDING"
  | "RELEASED"
  | "REVIEW_REQUIRED"
  | "CANCELED"
  | "FAILED";

export type SettlementReviewReason =
  | "missing_evidence"
  | "invalid_evidence_hash"
  | "seller_mismatch"
  | "agreement_mismatch"
  | "tracking_mismatch"
  | "delivery_in_future"
  | "inspection_not_elapsed"
  | "funding_mismatch"
  | "evidence_deadline_missed"
  | "ledger_incomplete"
  | "manual_flag"
  | "late_capture";

export type CancelReasonCode =
  | "buyer_rejected"
  | "buyer_cancelled"
  | "reviewer_cancelled";

export type SettlementEvidenceItem = {
  evidence_id: string;
  kind: string;
  sha256: string;
  media_type: string;
  size_bytes: number;
  original_filename: string;
  note?: string | null;
  created_at: string;
};

export type SettlementProjection = {
  transaction_id: string;
  run_id: string;
  state: SettlementState;
  last_seq: number;
  amount_cents: number;
  currency: string;
  buyer_id: string;
  seller_id: string;
  agreement_hash: string;
  agreement_version: number;
  seller_decision: {
    status: string;
    reported_at: string;
    reason_code?: string | null;
    note?: string | null;
  } | null;
  approval: {
    approved_by: string;
    approved_at: string;
    note?: string | null;
  } | null;
  cancellation: {
    reason_code: string;
    note?: string | null;
    at: string;
  } | null;
  funding: {
    status: string;
    provider_order_id?: string | null;
    capture_id?: string | null;
    payer_action_url?: string | null;
    completed_at?: string | null;
  } | null;
  purchase_order: {
    seller_order_id: string;
    tracking_number?: string | null;
    carrier?: string | null;
    eta?: string | null;
  } | null;
  evidence: {
    required: string[];
    received: string[];
    complete: boolean;
    deadline?: string | null;
    items: SettlementEvidenceItem[];
  } | null;
  verification: {
    status: string;
    reasons: string[];
    checked_at?: string | null;
    override_allowed: boolean;
  } | null;
  payout: {
    status: string;
    batch_id?: string | null;
    item_id?: string | null;
    amount_cents?: number | null;
    updated_at?: string | null;
  } | null;
  receipt_available: boolean;
  deadlines: {
    evidence?: string | null;
    inspection?: string | null;
  };
  allowed_actions: string[];
  updated_at: string;
  settlement_unavailable?: boolean;
};

export type SettlementReceipt = {
  payload: {
    receipt_version: number;
    transaction_id: string;
    agreement_hash: string;
    amount_cents: number;
    currency: string;
    buyer_id: string;
    seller_id: string;
    capture_id: string;
    payout_item_id: string;
    evidence_hashes: string[];
    released_at: string;
  };
  payload_hash: string;
  signature: string;
  kid: string;
  verified: boolean;
};

export type SettlementResponse = {
  run_id: string;
  settlement: SettlementProjection;
  interrupt?: Record<string, unknown> | null;
};

export type AgreementState =
  | "PENDING_SELLER"
  | "PENDING_BUYER"
  | "CHANGES_REQUESTED"
  | "AGREED"
  | "REJECTED"
  | "EXPIRED"
  | "TERMINATED";

export type AgreementDecisionKind =
  | "ACCEPT"
  | "REJECT"
  | "REQUEST_CHANGES"
  | "OPERATOR_REQUIRED";

export type RemedyTerms = {
  non_delivery: string;
  late_delivery: string;
  damaged_goods: string;
};

export type ChangeOperation = {
  op: string;
  sku?: string | null;
  unit_price_cents?: number | null;
  quantity?: number | null;
  shipping_cents?: number | null;
  tax_cents?: number | null;
  fees_cents?: number | null;
  delivery_days?: number | null;
  warranty_months?: number | null;
  returns_days?: number | null;
  inspection_period_hours?: number | null;
  evidence_required?: string[] | null;
  remedies?: RemedyTerms | null;
  dispute_window_hours?: number | null;
};

export type ChangeRequestView = {
  change_request_id: string;
  base_version: number;
  base_hash: string;
  requested_by_party: "buyer" | "seller";
  requested_by_actor_type: string;
  requested_by_actor_id: string;
  operations: ChangeOperation[];
  reason: string;
  status: "PENDING" | "ACCEPTED" | "REJECTED" | "EXPIRED";
  resolved_by_party?: "buyer" | "seller" | null;
  resolution_note: string;
  resulting_version?: number | null;
  created_at: string;
  resolved_at?: string | null;
};

export type AgreementDecisionView = {
  decision_id: string;
  party: "buyer" | "seller";
  decision: AgreementDecisionKind;
  actor_type: string;
  actor_id: string;
  authority_ref?: string | null;
  agreement_hash: string;
  version: number;
  note: string;
  decided_at: string;
};

export type AgreementVersionView = {
  version: number;
  agreement_hash: string;
  created_at: string;
  supersedes_version?: number | null;
  change_request_id?: string | null;
  superseded_at?: string | null;
  decisions: AgreementDecisionView[];
  is_current: boolean;
};

export type AgreementView = {
  agreement_id: string;
  transaction_id: string;
  run_id: string;
  buyer_id: string;
  seller_id: string;
  status: AgreementState;
  current_version: number;
  expires_at?: string | null;
  agreed_at?: string | null;
  offer_id: string;
  offer_round: number;
  offer_hash: string;
  offer_valid_until: string;
  seller_operator_required: boolean;
  version: AgreementVersionView;
  decisions: AgreementDecisionView[];
  change_request?: ChangeRequestView | null;
  review_url?: string | null;
};
