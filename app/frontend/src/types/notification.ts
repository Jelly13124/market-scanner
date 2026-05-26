// TypeScript types for the /notifications/* REST API.
// Mirror app/backend/models/notification_schemas.py.

export type NotificationChannel = 'email' | 'webhook';
export type DeliveryStatus = 'ok' | 'error';

export interface SubscriptionResponse {
  id: number;
  enabled: boolean;
  event_type: string;
  channel: NotificationChannel;
  target: string;
  label: string | null;
  has_auth_header: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface SubscriptionCreateRequest {
  channel: NotificationChannel;
  target: string;
  label?: string | null;
  enabled?: boolean;
  event_type?: string;
  auth_header?: string | null;
}

export interface SubscriptionPatchRequest {
  enabled?: boolean;
  target?: string;
  label?: string | null;
  auth_header?: string | null;
}

export interface DeliveryResponse {
  id: number;
  subscription_id: number;
  run_id: string | null;
  status: DeliveryStatus;
  http_code: number | null;
  error_text: string | null;
  latency_ms: number | null;
  attempted_at: string;
}
