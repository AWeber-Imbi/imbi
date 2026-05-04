import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Edit2, Info, type LucideIcon, Puzzle } from 'lucide-react'

import { getProjectTypeSchema } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DynamicDetailFields } from '@/components/ui/dynamic-fields'
import { PROJECT_TYPE_BASE_FIELDS_SET } from '@/lib/constants'
import { useIcon } from '@/lib/icons'
import { extractDynamicFields } from '@/lib/utils'
import type { ProjectType } from '@/types'

import { ProjectTypePlugins } from './ProjectTypePlugins'

type DetailTab = 'details' | 'plugins'

interface ProjectTypeDetailProps {
  onBack: () => void
  onEdit: () => void
  projectType: ProjectType
}

export function ProjectTypeDetail({
  onBack,
  onEdit,
  projectType,
}: ProjectTypeDetailProps) {
  const [activeTab, setActiveTab] = useState<DetailTab>('details')
  const { data: ptSchema } = useQuery({
    queryFn: ({ signal }) => getProjectTypeSchema(signal),
    queryKey: ['projectTypeSchema'],
    staleTime: 5 * 60 * 1000,
  })

  const HeaderIcon = useIcon(projectType.icon ?? null, null)

  const tabs: { icon: LucideIcon; id: DetailTab; label: string }[] = [
    { icon: Info, id: 'details', label: 'Details' },
    { icon: Puzzle, id: 'plugins', label: 'Plugins' },
  ]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button onClick={onBack} variant="outline">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back
          </Button>
          <div className="flex items-center gap-3">
            {projectType.icon && HeaderIcon ? (
              <HeaderIcon className="h-8 w-8" />
            ) : null}
            <CardTitle>{projectType.name}</CardTitle>
          </div>
        </div>
        <Button
          className="bg-action text-action-foreground hover:bg-action-hover"
          onClick={onEdit}
        >
          <Edit2 className="mr-2 h-4 w-4" />
          Edit Project Type
        </Button>
      </div>

      {/* Tabs */}
      <div className="border-b border-tertiary">
        <div className="flex gap-0">
          {tabs.map((tab) => {
            const Icon = tab.icon
            const isActive = activeTab === tab.id
            return (
              <button
                className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors ${
                  isActive
                    ? 'border-info text-info'
                    : 'border-transparent text-secondary hover:text-primary'
                }`}
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                type="button"
              >
                <Icon className="h-4 w-4" />
                {tab.label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Details Tab */}
      {activeTab === 'details' && (
        <Card>
          <CardHeader className="border-b px-6 py-5">
            {projectType.description && (
              <p className="text-sm text-secondary">
                {projectType.description}
              </p>
            )}
          </CardHeader>
          <CardContent className="p-6">
            <div className="grid grid-cols-2 gap-6">
              <div>
                <div className="text-sm text-secondary">Slug</div>
                <div className="mt-1 text-primary">
                  <code className="rounded bg-secondary px-2 py-1 text-sm text-primary">
                    {projectType.slug}
                  </code>
                </div>
              </div>
              <div>
                <div className="text-sm text-secondary">Organization</div>
                <div className="mt-1 text-primary">
                  {projectType.organization.name}
                </div>
              </div>
              {ptSchema && (
                <DynamicDetailFields
                  data={extractDynamicFields(
                    projectType,
                    PROJECT_TYPE_BASE_FIELDS_SET,
                  )}
                  schema={ptSchema}
                />
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Plugins Tab */}
      {activeTab === 'plugins' && (
        <ProjectTypePlugins
          orgSlug={projectType.organization.slug}
          ptSlug={projectType.slug}
        />
      )}
    </div>
  )
}
