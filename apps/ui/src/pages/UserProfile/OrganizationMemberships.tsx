import { Link } from 'react-router-dom'

import type { AdminUser } from '@/types'

interface OrgMembershipsProps {
  user: AdminUser
}

export function OrganizationMemberships({ user }: OrgMembershipsProps) {
  const orgs = user.organizations ?? []
  return (
    <section className="rounded-md border border-tertiary bg-primary p-4">
      <h2 className="mb-3 text-sm font-medium text-primary">Organizations</h2>
      {orgs.length === 0 ? (
        <p className="text-xs text-tertiary">No organization memberships.</p>
      ) : (
        <ul className="space-y-2">
          {orgs.map((m) => (
            <li
              className="flex items-center justify-between text-sm"
              key={m.organization_slug}
            >
              <Link
                className="text-primary hover:text-info"
                to={`/admin/organizations/${m.organization_slug}`}
              >
                {m.organization_name}
              </Link>
              <span className="rounded-sm border border-tertiary px-1.5 py-0.5 text-xs text-secondary">
                {m.role}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
