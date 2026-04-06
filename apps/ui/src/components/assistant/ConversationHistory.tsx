import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
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
    mutationFn: (id: string) => updateConversation(id, { is_archived: true }),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ['assistant', 'conversations'],
      }),
  })

  const handleDelete = (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    deleteMutation.mutate(id)
  }

  const handleArchive = (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    archiveMutation.mutate(id)
  }

  if (!showHistory) {
    return (
      <button
        onClick={() => setShowHistory(true)}
        className={`rounded flex items-center gap-1 px-2 py-1 text-xs ${
          isDarkMode
            ? 'text-gray-400 hover:bg-gray-700 hover:text-gray-300'
            : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
        }`}
      >
        <MessageSquare className="h-3 w-3" />
        History
      </button>
    )
  }

  return (
    <div
      className={`absolute left-0 right-0 top-full z-50 mt-1 max-h-64 overflow-y-auto rounded-lg border shadow-lg ${
        isDarkMode ? 'border-gray-700 bg-gray-800' : 'border-gray-200 bg-white'
      }`}
    >
      <div className="p-2">
        <button
          onClick={() => {
            onNewConversation()
            setShowHistory(false)
          }}
          className={`rounded flex w-full items-center gap-2 px-3 py-2 text-sm ${
            isDarkMode
              ? 'text-gray-300 hover:bg-gray-700'
              : 'text-gray-700 hover:bg-gray-100'
          }`}
        >
          <Plus className="h-4 w-4" />
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
            className={`rounded flex cursor-pointer items-center justify-between px-3 py-2 text-sm ${
              conv.id === currentConversationId
                ? isDarkMode
                  ? 'bg-gray-700 text-white'
                  : 'bg-blue-50 text-blue-900'
                : isDarkMode
                  ? 'text-gray-300 hover:bg-gray-700'
                  : 'text-gray-700 hover:bg-gray-100'
            }`}
          >
            <span className="flex-1 truncate">{conv.title ?? 'Untitled'}</span>
            <div className="ml-2 flex items-center gap-1">
              <button
                onClick={(e) => handleArchive(e, conv.id)}
                aria-label={`Archive ${conv.title ?? 'conversation'}`}
                className={`rounded p-1 ${
                  isDarkMode ? 'hover:bg-gray-600' : 'hover:bg-gray-200'
                }`}
              >
                <Archive className="h-3 w-3" />
              </button>
              <button
                onClick={(e) => handleDelete(e, conv.id)}
                aria-label={`Delete ${conv.title ?? 'conversation'}`}
                className={`rounded p-1 ${
                  isDarkMode
                    ? 'text-red-400 hover:bg-gray-600'
                    : 'text-red-500 hover:bg-gray-200'
                }`}
              >
                <Trash2 className="h-3 w-3" />
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
          className={`rounded w-full px-3 py-1 text-xs ${
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
