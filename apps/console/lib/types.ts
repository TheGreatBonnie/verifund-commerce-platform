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
    version?: string;
    supportedInterfaces?: Array<{
      url?: string;
      protocolBinding?: string;
      protocolVersion?: string;
    }>;
    capabilities?: {
      streaming?: boolean;
      extensions?: Array<{ uri?: string; required?: boolean }>;
    };
    securitySchemes?: Record<string, unknown>;
  };
};
