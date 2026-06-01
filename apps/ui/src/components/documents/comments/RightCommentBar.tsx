import { useLayoutEffect, useRef } from 'react'

import { MessageSquareDashed } from 'lucide-react'

import type { CommentThread } from '@/types/comments'

import { highlightTop } from './highlight'
import { MarginCommentCard } from './MarginCommentCard'

interface DraftThread {
  anchor: CommentThread['anchor']
  id: string
}

interface Props {
  articleRef: React.RefObject<HTMLElement | null>
  busy?: boolean
  containerRef: React.RefObject<HTMLDivElement | null>
  currentUserEmail: string
  displayNames?: Map<string, string>
  draft?: DraftThread | null
  focusedId: null | string
  lastVisit?: number
  layoutTick: number
  onAcknowledge: (threadId: string, commentId: string) => void
  onCancelDraft: () => void
  onDelete: (threadId: string, commentId: string) => void
  onEdit: (
    threadId: string,
    commentId: string,
    body: string,
    mentions: string[],
  ) => void
  onFocus: (threadId: null | string) => void
  onHover: (threadId: null | string) => void
  onReply: (threadId: string, body: string, mentions: string[]) => void
  onResolve: (threadId: string, resolved: boolean) => void
  onSubmitDraft: (body: string, mentions: string[]) => void
  /** Inline threads (anchored or orphaned) shown in the margin. */
  orphanedIds: Set<string>
  threads: CommentThread[]
}

const GAP = 12
const ORPHAN_FALLBACK_TOP = 0

interface StackItem {
  height: number
  id: string
  top: number
}

/**
 * Right-margin anchored comment cards. Measures each card's anchor offset
 * (highlight top) and its own height, then lays them out top-to-bottom with no
 * overlap, expanding around the focused card. Positions are written
 * imperatively via `transform: translateY(...)` with NO transition so they
 * track live re-measurement (scroll/resize/content) instead of fighting it.
 */
export function RightCommentBar({
  articleRef,
  busy,
  containerRef,
  currentUserEmail,
  displayNames,
  draft,
  focusedId,
  lastVisit,
  layoutTick,
  onAcknowledge,
  onCancelDraft,
  onDelete,
  onEdit,
  onFocus,
  onHover,
  onReply,
  onResolve,
  onSubmitDraft,
  orphanedIds,
  threads,
}: Props) {
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({})

  const draftThread = draft ? makeDraftThread(draft) : null
  const allCards: CommentThread[] = draftThread
    ? [...threads, draftThread]
    : threads
  const cardSig = allCards
    .map((t) => `${t.id}:${t.comments.length}:${t.resolved ? 'r' : 'o'}`)
    .join(',')

  // fallow-ignore-next-line complexity
  useLayoutEffect(() => {
    const container = containerRef.current
    const article = articleRef.current
    if (!container || !article) return
    if (!allCards.length) return

    const items = allCards
      .map((t) => ({
        height: cardRefs.current[t.id]?.offsetHeight ?? 90,
        id: t.id,
        top: highlightTop(article, container, t.id) ?? ORPHAN_FALLBACK_TOP,
      }))
      .sort((a, b) => a.top - b.top)

    const place = computeStack(items, focusedId)
    for (const id of Object.keys(place)) {
      const el = cardRefs.current[id]
      if (el) el.style.transform = `translateY(${place[id]}px)`
    }
    // Re-measures and snaps on scroll/resize (layoutTick), focus changes, and
    // any change to the card set. NO transition on transform — see file header.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cardSig, focusedId, layoutTick])

  if (!allCards.length) {
    return (
      <div className="text-tertiary px-2 py-8 text-center text-[12.5px]">
        <MessageSquareDashed className="text-tertiary mx-auto mb-2 size-5" />
        No inline comments yet.
        <br />
        Select text to start a thread.
      </div>
    )
  }

  return (
    <div className="relative min-h-full">
      {allCards.map((thread) => {
        const isDraft = thread.id === draft?.id
        return (
          <MarginCommentCard
            busy={busy}
            currentUserEmail={currentUserEmail}
            displayNames={displayNames}
            draft={isDraft}
            focused={thread.id === focusedId || isDraft}
            key={thread.id}
            lastVisit={lastVisit}
            onAcknowledge={(commentId) => onAcknowledge(thread.id, commentId)}
            onCancelDraft={onCancelDraft}
            onDelete={(commentId) => onDelete(thread.id, commentId)}
            onEdit={(commentId, body, mentions) =>
              onEdit(thread.id, commentId, body, mentions)
            }
            onFocus={() => onFocus(thread.id)}
            onHover={(hovered) => onHover(hovered ? thread.id : null)}
            onReply={(body, mentions) => onReply(thread.id, body, mentions)}
            onResolve={(resolved) => onResolve(thread.id, resolved)}
            onSubmitDraft={onSubmitDraft}
            orphaned={!isDraft && orphanedIds.has(thread.id)}
            ref={(el) => {
              cardRefs.current[thread.id] = el
            }}
            thread={thread}
          />
        )
      })}
    </div>
  )
}

/**
 * Lay items out top-to-bottom with no overlap. When one is focused it keeps its
 * exact anchor top and the others are pushed away from it; otherwise everything
 * cascades down from the first anchor. Negative results are shifted to >= 0.
 */
// fallow-ignore-next-line complexity
function computeStack(
  items: StackItem[],
  focusedId: null | string,
): Record<string, number> {
  const focusIdx = items.findIndex((it) => it.id === focusedId)
  const place =
    focusIdx >= 0 ? stackAround(items, focusIdx) : stackDown(items, 0, {})
  const values = Object.values(place)
  const min = values.length ? Math.min(...values) : 0
  if (min < 0) for (const id of Object.keys(place)) place[id] -= min
  return place
}

/** Build a draft thread object the card can render with an empty comment list. */
function makeDraftThread(draft: DraftThread): CommentThread {
  const now = new Date().toISOString()
  return {
    anchor: draft.anchor,
    comments: [],
    created_at: now,
    created_by: '',
    document_id: '',
    id: draft.id,
    kind: 'inline',
    resolved: false,
    resolved_at: null,
    resolved_by: null,
    updated_at: null,
  }
}

/** Pin the focused item to its anchor and stack the rest above and below it. */
function stackAround(
  items: StackItem[],
  focusIdx: number,
): Record<string, number> {
  const place: Record<string, number> = {}
  place[items[focusIdx].id] = items[focusIdx].top
  stackDown(
    items,
    focusIdx + 1,
    place,
    items[focusIdx].top + items[focusIdx].height + GAP,
  )
  let up = items[focusIdx].top - GAP
  for (let i = focusIdx - 1; i >= 0; i--) {
    place[items[i].id] = Math.min(items[i].top, up - items[i].height)
    up = place[items[i].id] - GAP
  }
  return place
}

/** Stack items[from..] downward from `cursor`, writing into `place`. */
function stackDown(
  items: StackItem[],
  from: number,
  place: Record<string, number>,
  cursor = 0,
): Record<string, number> {
  let c = cursor
  for (let i = from; i < items.length; i++) {
    place[items[i].id] = Math.max(items[i].top, c)
    c = place[items[i].id] + items[i].height + GAP
  }
  return place
}
