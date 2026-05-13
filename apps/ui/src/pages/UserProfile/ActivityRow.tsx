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
      <span className="text-tertiary mt-0.5 shrink-0">{pickIcon(record)}</span>
      <div className="min-w-0 flex-1">
        <p className="text-primary truncate text-sm">{record.summary}</p>
        <p className="text-tertiary mt-0.5 flex flex-wrap items-center gap-2 text-xs">
          <span>{formatRelativeDate(record.occurred_at)}</span>
          <span className="border-tertiary rounded-sm border px-1.5 py-0.5">
            {record.type}
          </span>
          {record.environment_slug && (
            <span className="border-tertiary rounded-sm border px-1.5 py-0.5">
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
        className="hover:bg-secondary block rounded-sm py-2"
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
    if (record.type === 'Deployed') return <Rocket className="size-4" />
    if (record.type === 'Rolled Back') return <RotateCcw className="size-4" />
    return <ActivityIcon className="size-4" />
  }
  switch (record.source) {
    case 'conversation':
      return <MessageSquare className="size-4" />
    case 'document':
      return <FileText className="size-4" />
    case 'events':
      return <Zap className="size-4" />
    case 'release':
      return <Tag className="size-4" />
    case 'upload':
      return <Paperclip className="size-4" />
  }
}
