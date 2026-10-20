import { useEffect, useMemo, useRef, useState } from 'react'

import { Link, useNavigate, useParams } from 'react-router-dom'

import { Minimize2, Search, SquarePen } from 'lucide-react'

import {
  AssistantComposer,
  AssistantThread,
} from '@/components/assistant/AssistantThread'
import { Navigation } from '@/components/Navigation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  assistantReturnPath,
  newAssistantConversation,
  openAssistantConversation,
  useAssistantConversations,
} from '@/hooks/useAssistantChat'
import { usePageTitle } from '@/hooks/usePageTitle'
import { cn } from '@/lib/utils'
import { useAssistantStore } from '@/stores/assistantStore'
import type { Conversation } from '@/types/assistant'

/** The assistant as a page: conversation list on the left, thread right. */
export function AssistantPage() {
  const { conversationId } = useParams<{ conversationId?: string }>()
  const navigate = useNavigate()
  const currentId = useAssistantStore((s) => s.currentConversationId)
  const setPanelOpen = useAssistantStore((s) => s.setExpanded)
  const { data: conversations = [], isLoading } = useAssistantConversations()
  const [filter, setFilter] = useState('')
  const [loadError, setLoadError] = useState(false)
  const title = conversations.find((c) => c.id === currentId)?.title
  usePageTitle(title || 'Assistant')

  useEffect(() => {
    setLoadError(false)
    if (!conversationId) return
    // A later conversation replaces this load; ignore its failure.
    let replaced = false
    openAssistantConversation(conversationId).catch(() => {
      if (!replaced) setLoadError(true)
    })
    return () => {
      replaced = true
    }
  }, [conversationId])

  // A first message creates the conversation; put its id in the URL.
  // Reads the param through a ref so that opening another conversation
  // (param changes first, store follows) does not navigate back.
  const paramRef = useRef(conversationId)
  paramRef.current = conversationId
  useEffect(() => {
    if (currentId && currentId !== paramRef.current) {
      navigate(`/assistant/${currentId}`, { replace: true })
    }
  }, [currentId, navigate])

  const groups = useMemo(
    () => groupByAge(filterByTitle(conversations, filter)),
    [conversations, filter],
  )

  const openInPanel = () => {
    setPanelOpen(true)
    navigate(assistantReturnPath())
  }

  return (
    <div className="bg-tertiary text-primary min-h-screen">
      <Navigation currentView="assistant" />
      <main className="flex h-screen pt-16">
        <aside className="border-tertiary bg-primary flex w-80 shrink-0 flex-col gap-3 border-r p-4">
          <Button
            asChild
            className="bg-action text-action-foreground hover:bg-action-hover"
            onClick={newAssistantConversation}
          >
            <Link to="/assistant">
              <SquarePen className="size-4" />
              New conversation
            </Link>
          </Button>
          <div className="relative">
            <Search className="text-tertiary absolute top-1/2 left-3 size-4 -translate-y-1/2" />
            <Input
              aria-label="Search conversations"
              className="pl-9"
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Search conversations"
              value={filter}
            />
          </div>
          <nav className="-mx-2 min-h-0 flex-1 overflow-y-auto">
            {isLoading && (
              <p className="text-tertiary px-2 text-sm">Loading…</p>
            )}
            {!isLoading && groups.length === 0 && (
              <p className="text-tertiary px-2 text-sm">
                {filter ? 'No matching conversations.' : 'No conversations.'}
              </p>
            )}
            {groups.map(([label, items]) => (
              <section className="mb-4" key={label}>
                <h2 className="text-tertiary mb-1 px-2 text-xs font-medium tracking-wide uppercase">
                  {label}
                </h2>
                {items.map((c) => (
                  <Link
                    className={cn(
                      'text-primary hover:bg-secondary block truncate rounded-md px-2 py-2 text-sm',
                      c.id === currentId && 'bg-secondary font-medium',
                    )}
                    key={c.id}
                    to={`/assistant/${c.id}`}
                  >
                    {c.title || 'Untitled'}
                  </Link>
                ))}
              </section>
            ))}
          </nav>
        </aside>
        <section className="flex min-w-0 flex-1 flex-col">
          <header className="border-tertiary bg-primary flex items-center gap-3 border-b px-6 py-3">
            <h1 className="text-primary min-w-0 flex-1 truncate text-lg font-medium">
              {title || 'New conversation'}
            </h1>
            <Button onClick={openInPanel} variant="ghost">
              <Minimize2 className="size-4" />
              Open in side panel
            </Button>
          </header>
          {loadError ? (
            <p className="text-danger flex-1 p-6 text-sm">
              Failed to load this conversation.
            </p>
          ) : (
            <AssistantThread className="px-6 py-6 [&>div]:mx-auto [&>div]:max-w-3xl" />
          )}
          {/* After a failed load the store still holds the previous
              conversation; do not let a message go there unseen. */}
          {!loadError && (
            <div className="border-tertiary border-t px-6 py-4">
              <div className="mx-auto max-w-3xl">
                <AssistantComposer autoFocus />
              </div>
            </div>
          )}
        </section>
      </main>
    </div>
  )
}

function filterByTitle(conversations: Conversation[], filter: string) {
  const needle = filter.trim().toLowerCase()
  if (!needle) return conversations
  return conversations.filter((c) =>
    (c.title ?? '').toLowerCase().includes(needle),
  )
}

const DAY = 86_400_000

/** Today, previous 7 days, older; keeps the API's newest-first order. */
function groupByAge(conversations: Conversation[]) {
  const startOfToday = new Date().setHours(0, 0, 0, 0)
  const groups = new Map<string, Conversation[]>()
  for (const c of conversations) {
    const t = new Date(c.updated_at).getTime()
    const label =
      t >= startOfToday
        ? 'Today'
        : t >= startOfToday - 7 * DAY
          ? 'Previous 7 days'
          : 'Older'
    groups.set(label, [...(groups.get(label) ?? []), c])
  }
  return [...groups.entries()]
}
