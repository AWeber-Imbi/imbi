import { ArrowLeft, Building2, Edit2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EntityIcon } from '@/components/ui/entity-icon'
import { formatDate } from '@/lib/formatDate'
import type { Organization } from '@/types'

interface OrganizationDetailProps {
  onBack: () => void
  onEdit: () => void
  organization: Organization
}

export function OrganizationDetail({
  onBack,
  onEdit,
  organization,
}: OrganizationDetailProps) {
  return (
    <div className="space-y-6">
      {/* Back button */}
      <div>
        <Button onClick={onBack} variant="outline">
          <ArrowLeft className="mr-2 size-4" />
          Back
        </Button>
      </div>

      {/* Organization info card */}
      <Card>
        <CardHeader className="flex flex-row items-start justify-between space-y-0 border-b px-6 py-5">
          <div className="flex items-center gap-3">
            {organization.icon ? (
              <EntityIcon
                className="size-8 rounded object-cover"
                icon={organization.icon}
              />
            ) : (
              <Building2 className="text-secondary size-6" />
            )}
            <div>
              <CardTitle>{organization.name}</CardTitle>
              <p className="text-secondary mt-1 text-sm">
                {organization.description || 'No description provided'}
              </p>
            </div>
          </div>
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            onClick={onEdit}
          >
            <Edit2 className="mr-2 size-4" />
            Edit Organization
          </Button>
        </CardHeader>

        <CardContent className="p-6">
          <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
            <div>
              <div className="text-secondary mb-1 text-sm">Slug</div>
              <code className="bg-secondary text-primary rounded px-2 py-1 text-sm">
                {organization.slug}
              </code>
            </div>

            <div>
              <div className="text-secondary mb-1 text-sm">Created</div>
              <div className="text-primary">
                {formatDate(organization.created_at)}
              </div>
            </div>

            {organization.updated_at && (
              <div>
                <div className="text-secondary mb-1 text-sm">Last Modified</div>
                <div className="text-primary">
                  {formatDate(organization.updated_at)}
                </div>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
