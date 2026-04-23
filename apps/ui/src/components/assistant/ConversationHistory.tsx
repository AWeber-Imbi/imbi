import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { MessageSquare, Plus, Archive, Trash2 } from 'lucide-react'
import {
  listConversations,
  deleteConversation,
  updateConversation,
} from '@/api/assistant'
import type { Conversation } from '@/types/assistant'
import { Button } from '@/components/ui/button'

interface ConversationHistoryProps {
  currentConversationId: string | null
  onSelectConversation: (id: string) => void
  onNewConversation: () => void
}

export function ConversationHistory({
  currentConversationId,
  onSelectConversation,
  onNewConversation,
}: ConversationHistoryProps) {
  const [showHistory, setShowHistory] = useState(false)
  const queryClient = useQueryClient()

  const { data: conversations = [] } = useQuery({
    queryKey: ['assistant', 'conversations'],
    queryFn: ({ signal }) => listConversations({ limit: 20 }, signal),
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
      <Button
        variant="ghost"
        onClick={() => setShowHistory(true)}
        className="h-auto gap-1 rounded px-2 py-1 text-xs text-secondary hover:bg-secondary hover:text-primary"
      >
        <MessageSquare className="h-3 w-3" />
        History
      </Button>
    )
  }

  return (
    <div className="absolute left-0 right-0 top-full z-50 mt-1 max-h-64 overflow-y-auto rounded-lg border border-border bg-card shadow-lg">
      <div className="p-2">
        <Button
          variant="ghost"
          onClick={() => {
            onNewConversation()
            setShowHistory(false)
          }}
          className="h-auto w-full justify-start rounded px-3 py-2 text-sm text-secondary hover:bg-secondary"
        >
          <Plus className="h-4 w-4" />
          New Conversation
        </Button>
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
            className={`flex cursor-pointer items-center justify-between rounded px-3 py-2 text-sm ${
              conv.id === currentConversationId
                ? 'bg-secondary text-primary'
                : 'text-secondary hover:bg-secondary'
            }`}
          >
            <span className="flex-1 truncate">{conv.title ?? 'Untitled'}</span>
            <div className="ml-2 flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                onClick={(e) => handleArchive(e, conv.id)}
                aria-label={`Archive ${conv.title ?? 'conversation'}`}
                className="h-auto w-auto rounded p-1 hover:bg-secondary"
              >
                <Archive className="h-3 w-3" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={(e) => handleDelete(e, conv.id)}
                aria-label={`Delete ${conv.title ?? 'conversation'}`}
                className="h-auto w-auto rounded p-1 text-danger hover:bg-secondary"
              >
                <Trash2 className="h-3 w-3" />
              </Button>
            </div>
          </div>
        ))}
      </div>
      <div className="border-t border-tertiary p-1">
        <Button
          variant="ghost"
          onClick={() => setShowHistory(false)}
          className="h-auto w-full rounded px-3 py-1 text-xs text-tertiary hover:text-secondary"
        >
          Close
        </Button>
      </div>
    </div>
  )
}
