export type BuyerTransactionSummary = {
  transaction_id: string;
  product_name?: string | null;
  seller_name?: string | null;
  seller_id?: string | null;
  agreed_amount_cents?: number | null;
  currency?: string | null;
  payment_status?: string | null;
  transaction_status?: string | null;
  fulfillment_status?: string | null;
  next_action?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  fulfillment?: {
    status?: string | null;
    next_action?: string | null;
  } | null;
};

export type BuyerTransactionListResponse = {
  items: BuyerTransactionSummary[];
  aggregates?: Record<string, number>;
  next_cursor?: string | null;
};

export type BuyerTransactionDetail = {
  transaction_id: string;
  status?: string | null;
  transaction_status?: string | null;
  payment_status?: string | null;
  seller_id?: string | null;
  seller_name?: string | null;
  agreed_amount_cents?: number | null;
  currency?: string | null;
  agreement?: Record<string, any> | null;
  payment?: Record<string, any> | null;
  timeline?: Array<Record<string, any>> | null;
  fulfillment?: {
    status?: string | null;
    next_action?: string | null;
    blockers?: Array<{ code: string; message?: string; owner?: string }>;
  } | null;
  [key: string]: any;
};

export type BuyerFulfillmentProjection = {
  transaction_id: string;
  fulfillment_id?: string | null; // reserved for future 1:N; null/undefined when transaction-keyed
  status?: string | null;
  next_action?: string | null;
  requirements?: Array<Record<string, any>>;
  evidence?: Array<Record<string, any>>;
  verification?: Array<Record<string, any>>;
  shipment?: Record<string, any> | null;
  carrier_events?: Array<Record<string, any>>;
  inspection?: Record<string, any> | null;
  disputes?: Array<Record<string, any>>;
  blockers?: Array<{ code: string; message?: string; owner?: string }>;
  allowed_actions?: string[];
  [key: string]: any;
};

export type BuyerInspection = {
  transaction_id?: string;
  status?: string | null;
  deadline_at?: string | null;
  deadline?: string | null;
  outcome?: string | null;
  [key: string]: any;
};
