import { Gravatar } from '@/components/ui/gravatar'
import { formatDate, formatRelativeDate } from '@/lib/formatDate'
import type { AdminUser } from '@/types'

import type { IdentitiesResponse } from './api'

interface ProfileHeaderProps {
  identities: IdentitiesResponse | undefined
  user: AdminUser
}

export function ProfileHeader({ identities, user }: ProfileHeaderProps) {
  const handle = user.email.split('@')[0]
  const primary = identities?.primary
  const externalSubject = primary
    ? `${primary.provider}-${primary.provider_user_id}`
    : null

  return (
    <header className="flex flex-col gap-4 border-b border-secondary pb-6 md:flex-row md:items-start md:gap-6">
      <Gravatar
        className="rounded-md border border-tertiary"
        email={user.email}
        size={96}
      />
      <div className="flex-1 space-y-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <h1 className="text-2xl font-semibold text-primary">
            {user.display_name}
          </h1>
          {primary?.provider && (
            <span className="rounded-sm border border-tertiary px-1.5 py-0.5 text-xs text-secondary">
              {primary.provider}
            </span>
          )}
          {user.is_service_account && (
            <span className="rounded-sm border border-tertiary px-1.5 py-0.5 text-xs text-secondary">
              service account
            </span>
          )}
          {!user.is_active && (
            <span className="rounded-sm border border-tertiary bg-danger px-1.5 py-0.5 text-xs text-danger">
              deactivated
            </span>
          )}
        </div>
        <p className="text-sm text-secondary">@{handle}</p>
        <p className="text-sm text-secondary">{user.email}</p>
        {externalSubject && (
          <p className="font-mono text-xs text-tertiary">{externalSubject}</p>
        )}
        <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-secondary">
          <div>
            <dt className="inline text-tertiary">Joined </dt>
            <dd className="inline">{formatDate(user.created_at)}</dd>
          </div>
          {user.last_login && (
            <div>
              <dt className="inline text-tertiary">Last active </dt>
              <dd className="inline">{formatRelativeDate(user.last_login)}</dd>
            </div>
          )}
        </dl>
      </div>
    </header>
  )
}
