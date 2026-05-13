import { Link } from 'react-router-dom'

import type { AdminUser } from '@/types'

interface OrgMembershipsProps {
  user: AdminUser
}

export function OrganizationMemberships({ user }: OrgMembershipsProps) {
  const orgs = user.organizations ?? []
  return (
    <section className="border-tertiary bg-primary rounded-md border p-4">
      <h2 className="text-primary mb-3 text-sm font-medium">Organizations</h2>
      {orgs.length === 0 ? (
        <p className="text-tertiary text-xs">No organization memberships.</p>
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
              <span className="border-tertiary text-secondary rounded-sm border px-1.5 py-0.5 text-xs">
                {m.role}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
