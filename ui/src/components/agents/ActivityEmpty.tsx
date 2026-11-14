import type { ReactNode } from 'react'

import { SearchX } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty'

import { SKIP_HIGHLIGHT } from './taskSearch'

/** What an Activity view shows when it has nothing to list. */
export function ActivityEmpty({
  children,
  icon,
  title,
}: {
  children: ReactNode
  icon: ReactNode
  title: string
}) {
  return (
    <Empty {...{ [SKIP_HIGHLIGHT]: '' }}>
      <EmptyHeader>
        <EmptyMedia variant="icon">{icon}</EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{children}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  )
}

/** What an Activity view shows when nothing in it matches the search. */
export function NoMatches({
  onClear,
  query,
}: {
  onClear: () => void
  query: string
}) {
  return (
    <Empty {...{ [SKIP_HIGHLIGHT]: '' }}>
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <SearchX />
        </EmptyMedia>
        <EmptyTitle>No matches</EmptyTitle>
        <EmptyDescription>
          Nothing in this view matches “{query.trim()}”.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button onClick={onClear} size="sm" variant="outline">
          Clear search
        </Button>
      </EmptyContent>
    </Empty>
  )
}
