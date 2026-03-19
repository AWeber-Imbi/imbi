import { create } from 'zustand'

interface ActiveToolUse {
  id: string
  name: string
  input: string
}

interface AssistantMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  toolUse?: ActiveToolUse[]
  isStreaming?: boolean
}

interface AssistantStore {
  isExpanded: boolean
  currentConversationId: string | null
  messages: AssistantMessage[]
  isStreaming: boolean
  streamingContent: string
  activeToolUse: ActiveToolUse | null
  pendingToolUses: ActiveToolUse[]

  setExpanded: (expanded: boolean) => void
  setCurrentConversation: (id: string | null) => void
  addMessage: (message: AssistantMessage) => void
  setMessages: (messages: AssistantMessage[]) => void
  startStreaming: () => void
  appendStreamingContent: (text: string) => void
  setActiveToolUse: (tool: ActiveToolUse | null) => void
  addPendingToolUse: (tool: ActiveToolUse) => void
  finishStreaming: (messageId: string) => void
  clearConversation: () => void
}

export const useAssistantStore = create<AssistantStore>()((set, get) => ({
  isExpanded: false,
  currentConversationId: null,
  messages: [],
  isStreaming: false,
  streamingContent: '',
  activeToolUse: null,
  pendingToolUses: [],

  setExpanded: (expanded) => set({ isExpanded: expanded }),

  setCurrentConversation: (id) =>
    set({
      currentConversationId: id,
      messages: [],
      isStreaming: false,
      streamingContent: '',
      activeToolUse: null,
      pendingToolUses: [],
    }),

  addMessage: (message) =>
    set((state) => ({
      messages: [...state.messages, message],
    })),

  setMessages: (messages) => set({ messages }),

  startStreaming: () =>
    set({
      isStreaming: true,
      streamingContent: '',
      activeToolUse: null,
      pendingToolUses: [],
    }),

  appendStreamingContent: (text) =>
    set((state) => ({
      streamingContent: state.streamingContent + text,
    })),

  setActiveToolUse: (tool) => set({ activeToolUse: tool }),

  addPendingToolUse: (tool) =>
    set((state) => ({
      pendingToolUses: [...state.pendingToolUses, tool],
    })),

  finishStreaming: (messageId) => {
    const state = get()
    const hasOutput =
      state.streamingContent.trim().length > 0 ||
      state.pendingToolUses.length > 0

    if (!hasOutput) {
      set({
        isStreaming: false,
        streamingContent: '',
        activeToolUse: null,
        pendingToolUses: [],
      })
      return
    }

    const assistantMessage: AssistantMessage = {
      id: messageId,
      role: 'assistant',
      content: state.streamingContent,
      timestamp: new Date(),
      toolUse:
        state.pendingToolUses.length > 0 ? state.pendingToolUses : undefined,
    }
    set({
      isStreaming: false,
      streamingContent: '',
      activeToolUse: null,
      pendingToolUses: [],
      messages: [...state.messages, assistantMessage],
    })
  },

  clearConversation: () =>
    set({
      currentConversationId: null,
      messages: [],
      streamingContent: '',
      isStreaming: false,
      activeToolUse: null,
      pendingToolUses: [],
    }),
}))
