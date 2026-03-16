export interface Conversation {
  id: string
  user_email: string
  title: string | null
  created_at: string
  updated_at: string
  model: string
  is_archived: boolean
}

export interface ConversationWithMessages extends Conversation {
  messages: Message[]
}

export interface Message {
  id: string
  conversation_id: string
  role: 'user' | 'assistant'
  content: string
  tool_use: ToolUseBlock[] | null
  tool_results: ToolResultBlock[] | null
  created_at: string
  sequence: number
  token_usage: TokenUsage | null
}

export interface ToolUseBlock {
  id: string
  name: string
  input: Record<string, unknown>
}

export interface ToolResultBlock {
  tool_use_id: string
  content: string
  is_error?: boolean
}

export interface TokenUsage {
  input_tokens: number
  output_tokens: number
}

// SSE event payloads
export interface SSETextEvent {
  text: string
}

export interface SSEToolUseStartEvent {
  id: string
  name: string
}

export interface SSEToolInputEvent {
  partial_json: string
}

export interface SSEDoneEvent {
  message_id: string
  usage: TokenUsage
}

export interface SSEErrorEvent {
  message: string
}

export interface SSEClientActionEvent {
  id: string
  action: 'navigate_to' | 'refresh_data'
  params: Record<string, string>
}

export interface CreateConversationRequest {
  model?: string
}

export interface SendMessageRequest {
  content: string
}

export interface UpdateConversationRequest {
  title?: string
  is_archived?: boolean
}
