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
    <header className="border-secondary flex flex-col gap-4 border-b pb-6 md:flex-row md:items-start md:gap-6">
      <Gravatar
        className="border-tertiary rounded-md border"
        email={user.email}
        size={96}
      />
      <div className="flex-1 space-y-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <h1 className="text-primary text-2xl font-semibold">
            {user.display_name}
          </h1>
          {primary?.provider && (
            <span className="border-tertiary text-secondary rounded-sm border px-1.5 py-0.5 text-xs">
              {primary.provider}
            </span>
          )}
          {user.is_service_account && (
            <span className="border-tertiary text-secondary rounded-sm border px-1.5 py-0.5 text-xs">
              service account
            </span>
          )}
          {!user.is_active && (
            <span className="border-tertiary bg-danger text-danger rounded-sm border px-1.5 py-0.5 text-xs">
              deactivated
            </span>
          )}
        </div>
        <p className="text-secondary text-sm">@{handle}</p>
        <p className="text-secondary text-sm">{user.email}</p>
        {externalSubject && (
          <p className="text-tertiary font-mono text-xs">{externalSubject}</p>
        )}
        <dl className="text-secondary mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs">
          <div>
            <dt className="text-tertiary inline">Joined </dt>
            <dd className="inline">{formatDate(user.created_at)}</dd>
          </div>
          {user.last_login && (
            <div>
              <dt className="text-tertiary inline">Last active </dt>
              <dd className="inline">{formatRelativeDate(user.last_login)}</dd>
            </div>
          )}
        </dl>
      </div>
    </header>
  )
}
