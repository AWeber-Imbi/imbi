import { Link } from 'react-router-dom'

import {
  Activity as ActivityIcon,
  FileText,
  MessageSquare,
  Paperclip,
  Rocket,
  RotateCcw,
  Tag,
  Zap,
} from 'lucide-react'

import { formatRelativeDate } from '@/lib/formatDate'

import type { ActivityRecord } from './api'

interface ActivityRowProps {
  record: ActivityRecord
}

export function ActivityRow({ record }: ActivityRowProps) {
  const body = (
    <div className="flex items-start gap-3">
      <span className="mt-0.5 flex-shrink-0 text-tertiary">
        {pickIcon(record)}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm text-primary">{record.summary}</p>
        <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-tertiary">
          <span>{formatRelativeDate(record.occurred_at)}</span>
          <span className="rounded-sm border border-tertiary px-1.5 py-0.5">
            {record.type}
          </span>
          {record.environment_slug && (
            <span className="rounded-sm border border-tertiary px-1.5 py-0.5">
              {record.environment_slug}
            </span>
          )}
        </p>
      </div>
    </div>
  )

  if (record.link) {
    return (
      <Link
        className="block rounded-sm py-2 hover:bg-secondary"
        to={record.link}
      >
        {body}
      </Link>
    )
  }
  return <div className="py-2">{body}</div>
}

function pickIcon(record: ActivityRecord) {
  if (record.source === 'operations_log') {
    if (record.type === 'Deployed') return <Rocket className="h-4 w-4" />
    if (record.type === 'Rolled Back') return <RotateCcw className="h-4 w-4" />
    return <ActivityIcon className="h-4 w-4" />
  }
  switch (record.source) {
    case 'conversation':
      return <MessageSquare className="h-4 w-4" />
    case 'events':
      return <Zap className="h-4 w-4" />
    case 'note':
      return <FileText className="h-4 w-4" />
    case 'release':
      return <Tag className="h-4 w-4" />
    case 'upload':
      return <Paperclip className="h-4 w-4" />
  }
}
