import { ArrowLeft, Edit2, Building2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EntityIcon } from '@/components/ui/entity-icon'
import { formatDate } from '@/lib/formatDate'
import type { Organization } from '@/types'

interface OrganizationDetailProps {
  organization: Organization
  onEdit: () => void
  onBack: () => void
}

export function OrganizationDetail({
  organization,
  onEdit,
  onBack,
}: OrganizationDetailProps) {
  return (
    <div className="space-y-6">
      {/* Back button */}
      <div>
        <Button variant="outline" onClick={onBack}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back
        </Button>
      </div>

      {/* Organization info card */}
      <Card>
        <CardHeader className="flex flex-row items-start justify-between space-y-0 border-b px-6 py-5">
          <div className="flex items-center gap-3">
            {organization.icon ? (
              <EntityIcon
                icon={organization.icon}
                className="h-8 w-8 rounded object-cover"
              />
            ) : (
              <Building2 className={'h-6 w-6 text-secondary'} />
            )}
            <div>
              <CardTitle>{organization.name}</CardTitle>
              <p className={'mt-1 text-sm text-secondary'}>
                {organization.description || 'No description provided'}
              </p>
            </div>
          </div>
          <Button
            onClick={onEdit}
            className="bg-action text-action-foreground hover:bg-action-hover"
          >
            <Edit2 className="mr-2 h-4 w-4" />
            Edit Organization
          </Button>
        </CardHeader>

        <CardContent className="p-6">
          <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
            <div>
              <div className={'mb-1 text-sm text-secondary'}>Slug</div>
              <code
                className={`rounded px-2 py-1 text-sm ${'bg-secondary text-primary'}`}
              >
                {organization.slug}
              </code>
            </div>

            <div>
              <div className={'mb-1 text-sm text-secondary'}>Created</div>
              <div className={'text-primary'}>
                {formatDate(organization.created_at)}
              </div>
            </div>

            {organization.updated_at && (
              <div>
                <div className={'mb-1 text-sm text-secondary'}>
                  Last Modified
                </div>
                <div className={'text-primary'}>
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
