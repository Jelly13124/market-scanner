export interface ChatMessage {
  id: number;
  strategy_id: number;
  created_at: string;
  role: 'user' | 'assistant' | 'user_manual_edit';
  content: string;
  spec_snapshot_json?: Record<string, unknown> | null;
  spec_patch_json?: Record<string, unknown> | null;
  patch_accepted?: boolean | null;
}

export interface ChatSendRequest {
  message: string;
}

export interface ChatResponse {
  message: ChatMessage;
  kind: 'reply' | 'patch';
  proposed_spec_json?: Record<string, unknown> | null;
}

export interface ChatApplyRequest {
  message_id: number;
}
