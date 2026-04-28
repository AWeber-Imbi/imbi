import { create } from 'zustand'

interface ActiveToolUse {
  id: string
  input: string
  name: string
}

interface AssistantMessage {
  content: string
  id: string
  isStreaming?: boolean
  role: 'assistant' | 'user'
  timestamp: Date
  toolUse?: ActiveToolUse[]
}

interface AssistantStore {
  activeToolUse: ActiveToolUse | null
  addMessage: (message: AssistantMessage) => void
  addPendingToolUse: (tool: ActiveToolUse) => void
  appendStreamingContent: (text: string) => void
  clearConversation: () => void
  currentConversationId: null | string
  finishStreaming: (messageId: string) => void

  isExpanded: boolean
  isStreaming: boolean
  messages: AssistantMessage[]
  pendingToolUses: ActiveToolUse[]
  setActiveToolUse: (tool: ActiveToolUse | null) => void
  setCurrentConversation: (id: null | string) => void
  setExpanded: (expanded: boolean) => void
  setMessages: (messages: AssistantMessage[]) => void
  startStreaming: () => void
  streamingContent: string
}

export const useAssistantStore = create<AssistantStore>()((set, get) => ({
  activeToolUse: null,
  addMessage: (message) =>
    set((state) => ({
      messages: [...state.messages, message],
    })),
  addPendingToolUse: (tool) =>
    set((state) => ({
      pendingToolUses: [...state.pendingToolUses, tool],
    })),
  appendStreamingContent: (text) =>
    set((state) => ({
      streamingContent: state.streamingContent + text,
    })),
  clearConversation: () =>
    set({
      activeToolUse: null,
      currentConversationId: null,
      isStreaming: false,
      messages: [],
      pendingToolUses: [],
      streamingContent: '',
    }),
  currentConversationId: null,
  finishStreaming: (messageId) => {
    const state = get()
    const hasOutput =
      state.streamingContent.trim().length > 0 ||
      state.pendingToolUses.length > 0

    if (!hasOutput) {
      set({
        activeToolUse: null,
        isStreaming: false,
        pendingToolUses: [],
        streamingContent: '',
      })
      return
    }

    const assistantMessage: AssistantMessage = {
      content: state.streamingContent,
      id: messageId,
      role: 'assistant',
      timestamp: new Date(),
      toolUse:
        state.pendingToolUses.length > 0 ? state.pendingToolUses : undefined,
    }
    set({
      activeToolUse: null,
      isStreaming: false,
      messages: [...state.messages, assistantMessage],
      pendingToolUses: [],
      streamingContent: '',
    })
  },

  isExpanded: false,

  isStreaming: false,

  messages: [],

  pendingToolUses: [],

  setActiveToolUse: (tool) => set({ activeToolUse: tool }),

  setCurrentConversation: (id) =>
    set({
      activeToolUse: null,
      currentConversationId: id,
      isStreaming: false,
      messages: [],
      pendingToolUses: [],
      streamingContent: '',
    }),

  setExpanded: (expanded) => set({ isExpanded: expanded }),

  setMessages: (messages) => set({ messages }),

  startStreaming: () =>
    set({
      activeToolUse: null,
      isStreaming: true,
      pendingToolUses: [],
      streamingContent: '',
    }),

  streamingContent: '',
}))
