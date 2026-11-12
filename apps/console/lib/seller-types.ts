export type RequirementCheck = {
  check_id: string;
  description: string;
  expected_value?: string | number | null;
  operator: string;
  unit?: string | null;
  verification_method: string;
  ai_derived: boolean;
};

export type Requirement = {
  requirement_id: string;
  title: string;
  description: string;
  owner: "seller" | "system" | "buyer" | string;
  kind: string;
  source: "file" | "reference" | "declaration" | string;
  accepted_formats: string[];
  checks: RequirementCheck[];
  required: boolean;
  stage?: string | null;
  min_items?: number;
  required_views?: string[];
};

export type RequirementCheckResult = {
  check_id: string;
  status: string;
  reasons: string[];
  observed_value?: string | number | null;
};

export type EvidenceItem = {
  evidence_id: string;
  requirement_id?: string | null;
  kind: string;
  sha256: string;
  media_type: string;
  size_bytes: number;
  original_filename: string;
  note?: string | null;
  origin?: string | null;
  attributed_to?: string | null;
  purpose?: string;
  captured_at?: string | null;
  scan_status?: string | null;
  agreement_version?: number | null;
  artifact_type?: string | null;
  reference?: string | null;
  submission_attempt?: number | null;
  view_label?: string | null;
  reason_code?: string | null;
  verification_method?: string | null;
  rule_version?: number | null;
  confidence?: number | null;
  created_at: string;
};

export type Blocker = {
  code: string;
  message: string;
  requirement_id?: string | null;
  action_owner?: string;
  severity?: string;
};

export type ProvenanceChallenge = {
  code: string;
  issued_at?: string | null;
  expires_at?: string | null;
  status?: string | null;
};

export type CarrierEvent = {
  provider_event_id?: string;
  normalized_status?: string;
  event_at?: string | null;
  received_at?: string | null;
  weight_g?: number | null;
  payload?: Record<string, unknown> | null;
  payload_json?: Record<string, unknown> | null;
  [key: string]: unknown;
};

export type ShipmentRecord = {
  id?: string;
  transaction_id?: string;
  carrier_key?: string;
  tracking_number?: string;
  service_level?: string | null;
  status?: string;
  scenario?: string | null;
  declared_value_minor?: number | null;
  insured_value_minor?: number | null;
  currency?: string | null;
  weight_expected_g?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
  [key: string]: unknown;
};

export type DeliveryConfirmation = {
  delivered_at?: string | null;
  recipient_reference?: string | null;
  signature_reference?: string | null;
  pod_reference?: string | null;
  weight_g?: number | null;
  payload_json?: Record<string, unknown> | null;
  [key: string]: unknown;
};

export type ShipmentState = {
  shipment?: ShipmentRecord | null;
  events?: CarrierEvent[];
  delivery_confirmation?: DeliveryConfirmation | null;
};

export type RequirementResult = {
  requirement_id: string;
  kind: string;
  owner: string;
  source: string;
  required?: boolean;
  status: string;
  checks: RequirementCheckResult[];
  submissions: EvidenceItem[];
  declared_at?: string | null;
  declared_by?: string | null;
  attempt?: number | null;
  reasons: string[];
  checked_at?: string | null;
  remediation?: Record<string, unknown> | null;
  action_owner?: string;
};

export type EvidenceSummary = {
  requirements: RequirementResult[];
  deadline?: string | null;
  items: EvidenceItem[];
};

export type SellerLineItem = {
  sku: string;
  name: string;
  quantity: number;
};

export type SellerEvidenceCount = {
  submitted: number;
  required: number;
  complete: boolean;
  received_kinds: string[];
};

export type SellerPayoutStatus = {
  status: string;
  amount_cents: number;
  updated_at?: string | null;
};

export type SellerTransactionSummary = {
  transaction_id: string;
  run_id: string;
  state: string;
  agreement_id?: string | null;
  agreement_version: number;
  amount_cents: number;
  currency: string;
  quantity: number;
  line_items: SellerLineItem[];
  delivery_days: number;
  warranty_months: number;
  returns_days: number;
  deadlines: Record<string, string | null>;
  evidence: SellerEvidenceCount;
  allowed_actions: string[];
  next_action: string;
  payout?: SellerPayoutStatus | null;
  updated_at: string;
};

export type SellerTransactionList = {
  items: SellerTransactionSummary[];
  counts_by_state: Record<string, number>;
  next_cursor?: string | null;
};

export type PurchaseOrderProjection = {
  seller_order_id: string;
  tracking_number?: string | null;
  carrier?: string | null;
  eta?: string | null;
};

export type PayoutProjection = {
  status: string;
  batch_id?: string | null;
  item_id?: string | null;
  amount_cents?: number | null;
  updated_at?: string | null;
};

export type DisputeProjection = {
  status: string;
  reason_code: string;
  claim_type?: string | null;
  requirement_ids: string[];
  claim: string;
  opened_at: string;
  escalation_rung: number;
  resolution?: string | null;
  resolved_at?: string | null;
  resolved_by?: string | null;
  rationale?: string | null;
};

export type SellerProjection = {
  transaction_id: string;
  run_id: string;
  state: string;
  seller_id: string;
  amount_cents: number;
  currency: string;
  agreement_id?: string | null;
  agreement_hash: string;
  agreement_version: number;
  quantity: number;
  line_items: Array<
    SellerLineItem & {
      unit_price_cents?: number;
      warranty_addon_cents?: number;
      attributes?: Record<string, string>;
    }
  >;
  delivery_days: number;
  warranty_months: number;
  returns_days: number;
  purchase_order?: PurchaseOrderProjection | null;
  evidence?: EvidenceSummary | null;
  requirements: Requirement[];
  payout?: PayoutProjection | null;
  dispute?: DisputeProjection | null;
  deadlines: Record<string, string | null>;
  blockers?: Blocker[];
  allowed_actions: string[];
  updated_at: string;
};

export type SellerEvidenceEntry = {
  evidence_id: string;
  transaction_id: string;
  requirement_id?: string | null;
  kind: string;
  media_type: string;
  size_bytes: number;
  original_filename: string;
  note?: string | null;
  captured_at?: string | null;
  created_at: string;
  scan_status?: string | null;
  transaction_state: string;
  verification?: {
    status?: string | null;
    reasons?: string[];
    checked_at?: string | null;
  } | null;
};

export type SellerEvidenceLibrary = {
  items: SellerEvidenceEntry[];
  next_cursor?: string | null;
};

export type SellerPayoutEntry = {
  transaction_id: string;
  amount_cents: number;
  currency: string;
  state: string;
  payout?: SellerPayoutStatus | null;
};

export type SellerPayoutTotals = {
  pending_cents: number;
  paid_cents: number;
  failed_cents: number;
};

export type SellerPayoutView = {
  transactions: SellerPayoutEntry[];
  totals: SellerPayoutTotals;
};

export type SellerEvent = {
  seq: number;
  type: string;
  payload: Record<string, unknown>;
  actor: string;
  created_at: string;
};

export type SellerEventsPage = {
  items: SellerEvent[];
  next_cursor?: string | null;
};

export type EvidenceReceipt = {
  submission_id: string;
  attempt: number;
  evidence_id: string;
  requirement_id: string;
  receipt_id: string;
  artifact_type: string;
  scan_status: string;
};

export type AgreementTerms = {
  totals?: {
    currency?: string;
    subtotal_cents?: number;
    shipping_cents?: number;
    tax_cents?: number;
    fees_cents?: number;
    total_cents?: number;
  };
  parties?: {
    buyer?: { id?: string; display_name?: string };
    seller?: { id?: string; display_name?: string };
  };
  items?: Array<{
    sku?: string;
    name?: string;
    quantity?: number;
    unit_price_cents?: number;
    warranty_addon_cents?: number;
  }>;
  delivery?: { delivery_days?: number; starts_on?: string };
  warranty_months?: number;
  returns_days?: number;
  inspection?: { period_hours?: number; starts_on?: string };
  remedies?: Record<string, string>;
  dispute_window_hours?: number;
  requirements?: Requirement[];
  [key: string]: unknown;
};

export type SellerAgreementView = {
  agreement_id: string;
  transaction_id: string;
  run_id: string;
  buyer_id: string;
  seller_id: string;
  status: string;
  current_version: number;
  expires_at?: string | null;
  agreed_at?: string | null;
  offer_id: string;
  offer_round: number;
  offer_hash: string;
  offer_valid_until: string;
  terms: AgreementTerms;
  version?: {
    version: number;
    agreement_hash: string;
    created_at: string;
    is_current: boolean;
  };
  [key: string]: unknown;
};
