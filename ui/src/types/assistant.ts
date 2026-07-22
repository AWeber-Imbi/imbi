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
