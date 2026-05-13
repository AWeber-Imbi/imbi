import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, MessageSquare, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  deleteConversation,
  listConversations,
  updateConversation,
} from '@/api/assistant'
import { Button } from '@/components/ui/button'
import { extractApiErrorDetail } from '@/lib/apiError'
import type { Conversation } from '@/types/assistant'

interface ConversationHistoryProps {
  currentConversationId: null | string
  onNewConversation: () => void
  onSelectConversation: (id: string) => void
}

export function ConversationHistory({
  currentConversationId,
  onNewConversation,
  onSelectConversation,
}: ConversationHistoryProps) {
  const [showHistory, setShowHistory] = useState(false)
  const queryClient = useQueryClient()

  const { data: conversations = [] } = useQuery({
    enabled: showHistory,
    queryFn: ({ signal }) => listConversations({ limit: 20 }, signal),
    queryKey: ['assistant', 'conversations'],
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteConversation(id),
    onError: (error: unknown) => {
      toast.error(
        `Failed to delete conversation: ${extractApiErrorDetail(error)}`,
      )
    },
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ['assistant', 'conversations'],
      }),
  })

  const archiveMutation = useMutation({
    mutationFn: (id: string) => updateConversation(id, { is_archived: true }),
    onError: (error: unknown) => {
      toast.error(
        `Failed to archive conversation: ${extractApiErrorDetail(error)}`,
      )
    },
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
        className="text-secondary hover:bg-secondary hover:text-primary h-auto gap-1 rounded px-2 py-1 text-xs"
        onClick={() => setShowHistory(true)}
        variant="ghost"
      >
        <MessageSquare className="size-3" />
        History
      </Button>
    )
  }

  return (
    <div className="border-border bg-card absolute top-full right-0 left-0 z-50 mt-1 max-h-64 overflow-y-auto rounded-lg border shadow-lg">
      <div className="p-2">
        <Button
          className="text-secondary hover:bg-secondary h-auto w-full justify-start rounded px-3 py-2 text-sm"
          onClick={() => {
            onNewConversation()
            setShowHistory(false)
          }}
          variant="ghost"
        >
          <Plus className="size-4" />
          New Conversation
        </Button>
        {conversations.map((conv: Conversation) => (
          <div
            className={`flex cursor-pointer items-center justify-between rounded px-3 py-2 text-sm ${
              conv.id === currentConversationId
                ? 'bg-secondary text-primary'
                : 'text-secondary hover:bg-secondary'
            }`}
            key={conv.id}
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
            role="button"
            tabIndex={0}
          >
            <span className="flex-1 truncate">{conv.title ?? 'Untitled'}</span>
            <div className="ml-2 flex items-center gap-1">
              <Button
                aria-label={`Archive ${conv.title ?? 'conversation'}`}
                className="hover:bg-secondary size-auto rounded p-1"
                onClick={(e) => handleArchive(e, conv.id)}
                size="icon"
                variant="ghost"
              >
                <Archive className="size-3" />
              </Button>
              <Button
                aria-label={`Delete ${conv.title ?? 'conversation'}`}
                className="text-danger hover:bg-secondary size-auto rounded p-1"
                onClick={(e) => handleDelete(e, conv.id)}
                size="icon"
                variant="ghost"
              >
                <Trash2 className="size-3" />
              </Button>
            </div>
          </div>
        ))}
      </div>
      <div className="border-tertiary border-t p-1">
        <Button
          className="text-tertiary hover:text-secondary h-auto w-full rounded px-3 py-1 text-xs"
          onClick={() => setShowHistory(false)}
          variant="ghost"
        >
          Close
        </Button>
      </div>
    </div>
  )
}
