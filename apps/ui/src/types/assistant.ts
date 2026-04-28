export interface Conversation {
  created_at: string
  id: string
  is_archived: boolean
  model: string
  title: null | string
  updated_at: string
  user_email: string
}

export interface ConversationWithMessages extends Conversation {
  messages: Message[]
}

export interface CreateConversationRequest {
  model?: string
}

export interface Message {
  content: string
  conversation_id: string
  created_at: string
  id: string
  role: 'assistant' | 'user'
  sequence: number
  token_usage: null | TokenUsage
  tool_results: null | ToolResultBlock[]
  tool_use: null | ToolUseBlock[]
}

export interface SendMessageRequest {
  content: string
}

export interface SSEClientActionEvent {
  action: 'navigate_to' | 'refresh_data'
  id: string
  params: Record<string, string>
}

export interface SSEDoneEvent {
  message_id: string
  usage: TokenUsage
}

export interface SSEErrorEvent {
  message: string
}

// SSE event payloads
export interface SSETextEvent {
  text: string
}

export interface SSEToolInputEvent {
  partial_json: string
}

export interface SSEToolUseStartEvent {
  id: string
  name: string
}

export interface TokenUsage {
  input_tokens: number
  output_tokens: number
}

export interface ToolResultBlock {
  content: string
  is_error?: boolean
  tool_use_id: string
}

export interface ToolUseBlock {
  id: string
  input: Record<string, unknown>
  name: string
}

export interface UpdateConversationRequest {
  is_archived?: boolean
  title?: string
}
