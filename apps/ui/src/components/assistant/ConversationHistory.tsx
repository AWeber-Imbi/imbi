import { useState } from 'react'
import {
  useQuery,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query'
import { MessageSquare, Plus, Archive, Trash2 } from 'lucide-react'
import {
  listConversations,
  deleteConversation,
  updateConversation,
} from '@/api/assistant'
import type { Conversation } from '@/types/assistant'

interface ConversationHistoryProps {
  isDarkMode: boolean
  currentConversationId: string | null
  onSelectConversation: (id: string) => void
  onNewConversation: () => void
}

export function ConversationHistory({
  isDarkMode,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
}: ConversationHistoryProps) {
  const [showHistory, setShowHistory] = useState(false)
  const queryClient = useQueryClient()

  const { data: conversations = [] } = useQuery({
    queryKey: ['assistant', 'conversations'],
    queryFn: () => listConversations({ limit: 20 }),
    enabled: showHistory,
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteConversation(id),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ['assistant', 'conversations'],
      }),
  })

  const archiveMutation = useMutation({
    mutationFn: (id: string) =>
      updateConversation(id, { is_archived: true }),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ['assistant', 'conversations'],
      }),
  })

  const handleDelete = (
    e: React.MouseEvent,
    id: string,
  ) => {
    e.stopPropagation()
    deleteMutation.mutate(id)
  }

  const handleArchive = (
    e: React.MouseEvent,
    id: string,
  ) => {
    e.stopPropagation()
    archiveMutation.mutate(id)
  }

  if (!showHistory) {
    return (
      <button
        onClick={() => setShowHistory(true)}
        className={`text-xs px-2 py-1 rounded flex items-center gap-1 ${
          isDarkMode
            ? 'text-gray-400 hover:text-gray-300 hover:bg-gray-700'
            : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
        }`}
      >
        <MessageSquare className="w-3 h-3" />
        History
      </button>
    )
  }

  return (
    <div
      className={`absolute top-full left-0 right-0 mt-1 rounded-lg border shadow-lg z-50 max-h-64 overflow-y-auto ${
        isDarkMode
          ? 'bg-gray-800 border-gray-700'
          : 'bg-white border-gray-200'
      }`}
    >
      <div className="p-2">
        <button
          onClick={() => {
            onNewConversation()
            setShowHistory(false)
          }}
          className={`w-full flex items-center gap-2 px-3 py-2 rounded text-sm ${
            isDarkMode
              ? 'text-gray-300 hover:bg-gray-700'
              : 'text-gray-700 hover:bg-gray-100'
          }`}
        >
          <Plus className="w-4 h-4" />
          New Conversation
        </button>
        {conversations.map((conv: Conversation) => (
          <div
            key={conv.id}
            role="button"
            tabIndex={0}
            onClick={() => {
              onSelectConversation(conv.id)
              setShowHistory(false)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                onSelectConversation(conv.id)
                setShowHistory(false)
              }
            }}
            className={`flex items-center justify-between px-3 py-2 rounded text-sm cursor-pointer ${
              conv.id === currentConversationId
                ? isDarkMode
                  ? 'bg-gray-700 text-white'
                  : 'bg-blue-50 text-blue-900'
                : isDarkMode
                  ? 'text-gray-300 hover:bg-gray-700'
                  : 'text-gray-700 hover:bg-gray-100'
            }`}
          >
            <span className="truncate flex-1">
              {conv.title ?? 'Untitled'}
            </span>
            <div className="flex items-center gap-1 ml-2">
              <button
                onClick={(e) => handleArchive(e, conv.id)}
                aria-label={`Archive ${conv.title ?? 'conversation'}`}
                className={`p-1 rounded ${
                  isDarkMode
                    ? 'hover:bg-gray-600'
                    : 'hover:bg-gray-200'
                }`}
              >
                <Archive className="w-3 h-3" />
              </button>
              <button
                onClick={(e) => handleDelete(e, conv.id)}
                aria-label={`Delete ${conv.title ?? 'conversation'}`}
                className={`p-1 rounded ${
                  isDarkMode
                    ? 'hover:bg-gray-600 text-red-400'
                    : 'hover:bg-gray-200 text-red-500'
                }`}
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          </div>
        ))}
      </div>
      <div
        className={`border-t p-1 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
      >
        <button
          onClick={() => setShowHistory(false)}
          className={`w-full text-xs px-3 py-1 rounded ${
            isDarkMode
              ? 'text-gray-500 hover:text-gray-400'
              : 'text-gray-400 hover:text-gray-600'
          }`}
        >
          Close
        </button>
      </div>
    </div>
  )
}
