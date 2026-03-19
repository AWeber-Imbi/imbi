import {
  Github,
  Bug,
  Bell,
  ExternalLink,
  icons,
  type LucideIcon,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card } from '@/components/ui/card'
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useOrganization } from '@/contexts/OrganizationContext'
import {
  listTeams,
  listProjectTypes,
  listEnvironments,
  listLinkDefinitions,
  createProject,
} from '@/api/endpoints'
import { slugify } from '@/lib/utils'
import type { ProjectCreate } from '@/types'

interface NewProjectDialogProps {
  isOpen: boolean
  onClose: () => void
  onProjectCreated?: (typeSlug: string, slug: string) => void
}

export function NewProjectDialog({
  isOpen,
  onClose,
  onProjectCreated,
}: NewProjectDialogProps) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''
  const queryClient = useQueryClient()
  const [step, setStep] = useState<'basic' | 'urls'>('basic')

  // Basic fields
  const [teamSlug, setTeamSlug] = useState('')
  const [projectTypeSlug, setProjectTypeSlug] = useState('')
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [description, setDescription] = useState('')
  const [selectedEnvSlugs, setSelectedEnvSlugs] = useState<string[]>([])

  // URL fields
  const [links, setLinks] = useState<Record<string, string>>({})

  // Automation toggles (mocked for now)
  const [createGithubRepo, setCreateGithubRepo] = useState(true)
  const [createSentryProject, setCreateSentryProject] = useState(true)
  const [createPagerdutyService, setCreatePagerdutyService] = useState(true)

  const { data: teams = [] } = useQuery({
    queryKey: ['teams', orgSlug],
    queryFn: () => listTeams(orgSlug),
    enabled: !!orgSlug && isOpen,
  })

  const { data: projectTypes = [] } = useQuery({
    queryKey: ['projectTypes', orgSlug],
    queryFn: () => listProjectTypes(orgSlug),
    enabled: !!orgSlug && isOpen,
  })

  const { data: environments = [] } = useQuery({
    queryKey: ['environments', orgSlug],
    queryFn: () => listEnvironments(orgSlug),
    enabled: !!orgSlug && isOpen,
  })

  const { data: linkDefs = [] } = useQuery({
    queryKey: ['linkDefinitions', orgSlug],
    queryFn: () => listLinkDefinitions(orgSlug),
    enabled: !!orgSlug && isOpen,
  })

  const createMutation = useMutation({
    mutationFn: ({
      typeSlug,
      data,
    }: {
      typeSlug: string
      data: ProjectCreate
    }) => createProject(orgSlug, typeSlug, data),
    onSuccess: (created, { typeSlug }) => {
      queryClient.invalidateQueries({ queryKey: ['projects', orgSlug] })
      onProjectCreated?.(typeSlug, created.slug)
      handleClose()
    },
  })

  const handleNameChange = (value: string) => {
    setName(value)
    if (!slug || slug === slugify(name)) {
      setSlug(slugify(value))
    }
  }

  const handleLinkChange = (key: string, value: string) => {
    setLinks((prev) => {
      if (!value) {
        const next = { ...prev }
        delete next[key]
        return next
      }
      return { ...prev, [key]: value }
    })
  }

  const toggleEnv = (envSlug: string) => {
    setSelectedEnvSlugs((prev) =>
      prev.includes(envSlug)
        ? prev.filter((s) => s !== envSlug)
        : [...prev, envSlug],
    )
  }

  const handleSave = () => {
    if (!orgSlug || !canProceed || createMutation.isPending) return
    const projectData: ProjectCreate = {
      name,
      slug,
      description: description || null,
      team_slug: teamSlug,
      environment_slugs:
        selectedEnvSlugs.length > 0 ? selectedEnvSlugs : undefined,
      links: Object.keys(links).length > 0 ? links : undefined,
    }
    createMutation.mutate({ typeSlug: projectTypeSlug, data: projectData })
  }

  const handleClose = () => {
    setStep('basic')
    setTeamSlug('')
    setProjectTypeSlug('')
    setName('')
    setSlug('')
    setDescription('')
    setSelectedEnvSlugs([])
    setLinks({})
    setCreateGithubRepo(true)
    setCreateSentryProject(true)
    setCreatePagerdutyService(true)
    onClose()
  }

  const canProceed = teamSlug && projectTypeSlug && name && slug

  if (!isOpen) return null

  const linkFields = linkDefs.map((ld) => {
    const pascalName = (ld.icon || '')
      .split('-')
      .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
      .join('') as keyof typeof icons
    const Icon = icons[pascalName] || ExternalLink
    const placeholder = ld.url_template || 'https://example.com/...'
    return { key: ld.slug, label: ld.name, icon: Icon, placeholder }
  })

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      role="dialog"
      aria-modal="true"
      aria-label="Create New Project"
      onKeyDown={(e) => {
        if (e.key === 'Escape') handleClose()
      }}
    >
      <div className="fixed inset-0 bg-black/50" onClick={handleClose} />
      <div className="relative mx-4 flex max-h-[90vh] w-full max-w-2xl flex-col rounded-lg bg-white shadow-xl">
        {/* Header */}
        <div className="border-b p-6">
          <h2 className="text-lg font-semibold text-slate-900">
            Create New Project
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            Create a new project with the following details.
          </p>
        </div>

        {/* Tab Switcher */}
        <div className="px-6 pt-4">
          <div className="grid grid-cols-2 gap-1 rounded-lg bg-slate-100 p-1">
            <button
              onClick={() => setStep('basic')}
              className={`rounded-md px-4 py-2 text-sm transition-colors ${
                step === 'basic'
                  ? 'bg-white text-slate-900 shadow'
                  : 'text-slate-600'
              }`}
            >
              Basic Information
            </button>
            <button
              onClick={() => canProceed && setStep('urls')}
              className={`rounded-md px-4 py-2 text-sm transition-colors ${
                step === 'urls'
                  ? 'bg-white text-slate-900 shadow'
                  : 'text-slate-600'
              } ${!canProceed ? 'cursor-not-allowed opacity-50' : ''}`}
            >
              URLs & Links
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {step === 'basic' ? (
            <div className="space-y-6">
              {/* Team */}
              <div className="space-y-2">
                <label
                  htmlFor="new-project-team"
                  className="text-sm font-medium text-slate-900"
                >
                  Team <span className="text-red-500">*</span>
                </label>
                <select
                  id="new-project-team"
                  value={teamSlug}
                  onChange={(e) => setTeamSlug(e.target.value)}
                  className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm"
                >
                  <option value="">Select team...</option>
                  {teams.map((t) => (
                    <option key={t.slug} value={t.slug}>
                      {t.name}
                    </option>
                  ))}
                </select>
                <p className="text-sm text-slate-500">
                  Team that owns this project
                </p>
              </div>

              {/* Project Type */}
              <div className="space-y-2">
                <label
                  htmlFor="new-project-type"
                  className="text-sm font-medium text-slate-900"
                >
                  Project Type <span className="text-red-500">*</span>
                </label>
                <select
                  id="new-project-type"
                  value={projectTypeSlug}
                  onChange={(e) => setProjectTypeSlug(e.target.value)}
                  className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm"
                >
                  <option value="">Select project type...</option>
                  {projectTypes.map((pt) => (
                    <option key={pt.slug} value={pt.slug}>
                      {pt.name}
                    </option>
                  ))}
                </select>
                <p className="text-sm text-slate-500">
                  Type of the new project
                </p>
              </div>

              {/* Name */}
              <div className="space-y-2">
                <label
                  htmlFor="new-project-name"
                  className="text-sm font-medium text-slate-900"
                >
                  Name <span className="text-red-500">*</span>
                </label>
                <Input
                  id="new-project-name"
                  value={name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., My Service"
                />
                <p className="text-sm text-slate-500">
                  Human-readable name for this project
                </p>
              </div>

              {/* Slug */}
              <div className="space-y-2">
                <label
                  htmlFor="new-project-slug"
                  className="text-sm font-medium text-slate-900"
                >
                  Slug <span className="text-red-500">*</span>
                </label>
                <Input
                  id="new-project-slug"
                  value={slug}
                  onChange={(e) => setSlug(e.target.value)}
                  placeholder="e.g., my-service"
                />
                <p className="text-sm text-slate-500">
                  URL-friendly identifier for this project
                </p>
              </div>

              {/* Description */}
              <div className="space-y-2">
                <label
                  htmlFor="new-project-description"
                  className="text-sm font-medium text-slate-900"
                >
                  Description
                </label>
                <textarea
                  id="new-project-description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Provide a high-level purpose and context for the project"
                  className="min-h-[120px] w-full resize-none rounded-md border border-slate-200 px-3 py-2 text-sm"
                />
              </div>

              {/* Environments */}
              {environments.length > 0 && (
                <div className="space-y-2">
                  <label className="text-sm font-medium text-slate-900">
                    Environments
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {environments.map((env) => (
                      <button
                        key={env.slug}
                        onClick={() => toggleEnv(env.slug)}
                        className={`rounded-md border px-3 py-1.5 text-sm transition-colors ${
                          selectedEnvSlugs.includes(env.slug)
                            ? 'border-blue-300 bg-blue-50 text-blue-700'
                            : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
                        }`}
                      >
                        {env.name}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Automations (mocked) */}
              <div className="space-y-2 border-t pt-4">
                <label className="text-sm font-medium text-slate-900">
                  Automations
                </label>
                <AutomationToggle
                  icon={Github}
                  title="Create GitHub Repository"
                  description="Automatically create a GitHub repository for this project"
                  checked={createGithubRepo}
                  onChange={setCreateGithubRepo}
                />
                <AutomationToggle
                  icon={Bug}
                  title="Create Sentry Project"
                  description="Automatically create a Sentry project for this project"
                  checked={createSentryProject}
                  onChange={setCreateSentryProject}
                />
                <AutomationToggle
                  icon={Bell}
                  title="Create PagerDuty Service"
                  description="Automatically create a PagerDuty service for this project"
                  checked={createPagerdutyService}
                  onChange={setCreatePagerdutyService}
                />
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              <p className="text-sm text-slate-500">
                Configure external links and integrations for this project. All
                fields are optional.
              </p>
              {linkFields.map(({ key, label, icon: Icon, placeholder }) => (
                <div key={key} className="space-y-2">
                  <label className="flex items-center gap-2 text-sm font-medium text-slate-900">
                    <Icon className="h-4 w-4 text-slate-500" />
                    {label}
                  </label>
                  <Input
                    type="url"
                    value={links[key] || ''}
                    onChange={(e) => handleLinkChange(key, e.target.value)}
                    placeholder={placeholder}
                  />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Error display */}
        {createMutation.error && (
          <div className="px-6 py-2">
            <Card className="border-red-200 bg-red-50 p-3">
              <p className="text-sm text-red-700">
                Failed to create project: {String(createMutation.error)}
              </p>
            </Card>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between border-t p-6">
          <div>
            {step === 'urls' && (
              <Button variant="ghost" onClick={() => setStep('basic')}>
                Back
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={handleClose}>
              Cancel
            </Button>
            {step === 'basic' ? (
              <Button onClick={() => setStep('urls')} disabled={!canProceed}>
                Next
              </Button>
            ) : (
              <Button onClick={handleSave} disabled={createMutation.isPending}>
                {createMutation.isPending ? 'Creating...' : 'Save'}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function AutomationToggle({
  icon: Icon,
  title,
  description,
  checked,
  onChange,
}: {
  icon: LucideIcon
  title: string
  description: string
  checked: boolean
  onChange: (val: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 p-4">
      <div className="flex items-center gap-3">
        <Icon className="h-5 w-5 text-slate-600" />
        <div>
          <p className="text-sm text-slate-900">{title}</p>
          <p className="text-xs text-slate-500">{description}</p>
        </div>
      </div>
      <button
        role="switch"
        aria-checked={checked}
        aria-label={title}
        onClick={() => onChange(!checked)}
        className={`relative h-5 w-9 rounded-full transition-colors ${
          checked ? 'bg-blue-600' : 'bg-slate-300'
        }`}
      >
        <span
          className={`absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
            checked ? 'translate-x-4' : 'translate-x-0'
          }`}
        />
      </button>
    </div>
  )
}
