import { useLayoutEffect } from 'react'

import { useLocation, useNavigate } from 'react-router-dom'

import { History, Maximize2, SquarePen, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  newAssistantConversation,
  openAssistantConversation,
  useAssistantConversations,
} from '@/hooks/useAssistantChat'
import { useAssistantStore } from '@/stores/assistantStore'

import { AssistantComposer, AssistantThread } from './AssistantThread'

const PANEL_WIDTH = 440

/**
 * The assistant docked on the right of every page. Page content keeps its
 * own layout: the body pads by --assistant-width while the panel is open.
 */
export function AssistantPanel() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const isOpen = useAssistantStore((s) => s.isExpanded)
  const setOpen = useAssistantStore((s) => s.setExpanded)
  const conversationId = useAssistantStore((s) => s.currentConversationId)
  const { data: conversations = [] } = useAssistantConversations()
  // The full-page assistant shows the same conversation.
  const visible = isOpen && !pathname.startsWith('/assistant')
  const title = conversations.find((c) => c.id === conversationId)?.title

  useLayoutEffect(() => {
    document.documentElement.style.setProperty(
      '--assistant-width',
      visible ? `${PANEL_WIDTH}px` : '0px',
    )
  }, [visible])

  if (!visible) return null

  return (
    <aside
      aria-label="Assistant"
      className="border-tertiary bg-primary fixed top-16 right-0 bottom-0 z-40 flex flex-col border-l"
      onKeyDown={(e) => {
        if (e.key === 'Escape') setOpen(false)
      }}
      style={{ width: PANEL_WIDTH }}
    >
      <header className="border-tertiary flex items-center gap-1 border-b px-4 py-2">
        <div className="min-w-0 flex-1">
          <div className="text-primary text-sm font-medium">Assistant</div>
          {title && (
            <div className="text-tertiary truncate text-xs">{title}</div>
          )}
        </div>
        <DropdownMenu modal={false}>
          <DropdownMenuTrigger asChild>
            <Button
              aria-label="History"
              size="icon"
              title="History"
              variant="ghost"
            >
              <History className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-72">
            <DropdownMenuLabel>Recent conversations</DropdownMenuLabel>
            {conversations.slice(0, 10).map((c) => (
              <DropdownMenuItem
                key={c.id}
                onClick={() => void openAssistantConversation(c.id)}
              >
                <span className="truncate">{c.title || 'Untitled'}</span>
              </DropdownMenuItem>
            ))}
            <DropdownMenuItem onClick={() => navigate('/assistant')}>
              <span className="text-tertiary">All conversations…</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Button
          aria-label="New conversation"
          onClick={newAssistantConversation}
          size="icon"
          title="New conversation"
          variant="ghost"
        >
          <SquarePen className="size-4" />
        </Button>
        <Button
          aria-label="Open full page"
          onClick={() =>
            navigate(
              conversationId ? `/assistant/${conversationId}` : '/assistant',
            )
          }
          size="icon"
          title="Open full page"
          variant="ghost"
        >
          <Maximize2 className="size-4" />
        </Button>
        <Button
          aria-label="Close assistant"
          onClick={() => setOpen(false)}
          size="icon"
          title="Close"
          variant="ghost"
        >
          <X className="size-4" />
        </Button>
      </header>
      <AssistantThread className="px-4 py-4" />
      <div className="border-tertiary border-t p-3">
        <AssistantComposer autoFocus />
      </div>
    </aside>
  )
}
