import { type ComponentType, useEffect, useState } from 'react'

import { Link, useNavigate, useParams } from 'react-router-dom'

import {
  Blocks,
  Bot,
  Building2,
  CalendarClock,
  ChevronLeft,
  ChevronRight,
  FileCode2,
  FileJson,
  FolderTree,
  Globe,
  KeyRound,
  Layers,
  LayoutDashboard,
  Link2,
  LockKeyhole,
  MessagesSquare,
  Network,
  Puzzle,
  Shield,
  SlidersHorizontal,
  Sparkles,
  StickyNote,
  Target,
  Users,
  UsersRound,
  Webhook,
  Wrench,
} from 'lucide-react'

import { agentsPath, type AgentsSection } from '@/components/agents/agentsNav'
import { Button } from '@/components/ui/button'
import { useOrganization } from '@/contexts/OrganizationContext'

import { AdminOverview } from './admin/AdminOverview'
import { AIModelsManagement } from './admin/AIModelsManagement'
import { AssistantManagement } from './admin/AssistantManagement'
import { AuthProvidersManagement } from './admin/AuthProvidersManagement'
import { BlueprintManagement } from './admin/BlueprintManagement'
import { DefaultSettingsManagement } from './admin/DefaultSettingsManagement'
import { DocumentTemplateManagement } from './admin/DocumentTemplateManagement'
import { EnvironmentManagement } from './admin/EnvironmentManagement'
import { GraphQueryManagement } from './admin/GraphQueryManagement'
import { IntegrationsManagement } from './admin/integrations/IntegrationsManagement'
import { LinkDefinitionManagement } from './admin/LinkDefinitionManagement'
import { MaintenanceManagement } from './admin/MaintenanceManagement'
import { OrganizationManagement } from './admin/OrganizationManagement'
import { PluginsManagement } from './admin/PluginsManagement'
import { ProjectTypeManagement } from './admin/ProjectTypeManagement'
import { RoleManagement } from './admin/RoleManagement'
import { ScheduledJobsManagement } from './admin/ScheduledJobsManagement'
import { ScoringPolicyManagement } from './admin/ScoringPolicyManagement'
import { SecretsManagement } from './admin/secrets/SecretsManagement'
import { ServiceAccountManagement } from './admin/ServiceAccountManagement'
import { TeamManagement } from './admin/TeamManagement'
import { UserManagement } from './admin/UserManagement'
import { Webhooks } from './admin/Webhooks'
import { PromptLibrary } from './prompts/PromptLibrary'

interface SectionDef {
  component: ComponentType
  description: string
  /** The sidebar heading. An empty group has no heading. */
  group: string
  icon: typeof Users
  id: string
  label: string
  scope: 'org' | 'system'
}

// The sidebar shows the sections in this order. Each group shows where
// its first section occurs.
const SECTIONS: SectionDef[] = [
  {
    component: AdminOverview,
    description: 'Operations metrics and system health at a glance',
    group: '',
    icon: LayoutDashboard,
    id: 'overview',
    label: 'Overview',
    scope: 'org',
  },
  {
    component: ProjectTypeManagement,
    description: 'Manage project types',
    group: 'Catalog',
    icon: FolderTree,
    id: 'project-types',
    label: 'Project Types',
    scope: 'org',
  },
  {
    component: EnvironmentManagement,
    description: 'Manage environments',
    group: 'Catalog',
    icon: Layers,
    id: 'environments',
    label: 'Environments',
    scope: 'org',
  },
  {
    component: BlueprintManagement,
    description: 'Configure metadata templates',
    group: 'Catalog',
    icon: FileJson,
    id: 'blueprints',
    label: 'Blueprints',
    scope: 'org',
  },
  {
    component: LinkDefinitionManagement,
    description: 'Manage link definitions for projects',
    group: 'Catalog',
    icon: Link2,
    id: 'link-definitions',
    label: 'Link Definitions',
    scope: 'org',
  },
  {
    component: DocumentTemplateManagement,
    description: 'Manage reusable document templates',
    group: 'Catalog',
    icon: StickyNote,
    id: 'document-templates',
    label: 'Document Templates',
    scope: 'org',
  },
  {
    component: ScoringPolicyManagement,
    description:
      'Define attribute, presence, link, and age-based scoring policies',
    group: 'Catalog',
    icon: Target,
    id: 'scoring-policies',
    label: 'Scoring Policies',
    scope: 'org',
  },
  {
    component: DefaultSettingsManagement,
    description: 'Organization-wide defaults, including version formats',
    group: 'Catalog',
    icon: SlidersHorizontal,
    id: 'default-settings',
    label: 'Defaults',
    scope: 'org',
  },
  {
    component: TeamManagement,
    description: 'Manage teams',
    group: 'People',
    icon: UsersRound,
    id: 'teams',
    label: 'Teams',
    scope: 'org',
  },
  {
    component: IntegrationsManagement,
    description: 'Connect external platforms',
    group: 'Connections',
    icon: Blocks,
    id: 'integrations',
    label: 'Integrations',
    scope: 'org',
  },
  {
    component: Webhooks,
    description: 'Inbound endpoints and their delivery activity',
    group: 'Connections',
    icon: Webhook,
    id: 'webhooks',
    label: 'Webhooks',
    scope: 'org',
  },
  {
    component: SecretsManagement,
    description: 'Secret providers, bindings, grants, and their audit',
    group: 'Connections',
    icon: LockKeyhole,
    id: 'secrets',
    label: 'Secrets',
    scope: 'org',
  },
  {
    component: UserManagement,
    description: 'Manage user accounts and administrators',
    group: 'Access',
    icon: Users,
    id: 'users',
    label: 'Users',
    scope: 'system',
  },
  {
    component: ServiceAccountManagement,
    description: 'Manage service accounts and API keys',
    group: 'Access',
    icon: Bot,
    id: 'service-accounts',
    label: 'Service Accounts',
    scope: 'system',
  },
  {
    component: RoleManagement,
    description: 'Define roles and permission collections',
    group: 'Access',
    icon: Shield,
    id: 'roles',
    label: 'Roles',
    scope: 'system',
  },
  {
    component: OrganizationManagement,
    description: 'Manage organizational units and access',
    group: 'Access',
    icon: Building2,
    id: 'organizations',
    label: 'Organizations',
    scope: 'system',
  },
  {
    component: AuthProvidersManagement,
    description: 'Configure SSO authentication providers',
    group: 'Access',
    icon: KeyRound,
    id: 'oauth',
    label: 'Auth Providers',
    scope: 'system',
  },
  {
    component: AIModelsManagement,
    description:
      'LLM providers and the model catalog, shared by every organization',
    group: 'AI',
    icon: Sparkles,
    id: 'ai-models',
    label: 'AI Models',
    scope: 'system',
  },
  {
    component: PromptLibrary,
    description: 'Versioned prompts, labels, and model settings',
    group: 'AI',
    icon: FileCode2,
    id: 'prompts',
    label: 'Prompts',
    scope: 'system',
  },
  {
    component: AssistantManagement,
    description: 'Configure the AI assistant and its MCP servers',
    group: 'AI',
    icon: MessagesSquare,
    id: 'assistant',
    label: 'Assistant',
    scope: 'system',
  },
  {
    component: PluginsManagement,
    description: 'Manage installed plugins',
    group: 'System',
    icon: Puzzle,
    id: 'plugins',
    label: 'Plugins',
    scope: 'system',
  },
  {
    component: MaintenanceManagement,
    description: 'Run global background maintenance operations',
    group: 'System',
    icon: Wrench,
    id: 'maintenance',
    label: 'Maintenance',
    scope: 'system',
  },
  {
    component: ScheduledJobsManagement,
    description: 'Jobs that imbi-scheduler fires on a schedule',
    group: 'System',
    icon: CalendarClock,
    id: 'scheduled-jobs',
    label: 'Scheduled jobs',
    scope: 'system',
  },
  {
    component: GraphQueryManagement,
    description: 'Run ad-hoc Cypher queries against the graph database',
    group: 'System',
    icon: Network,
    id: 'graph-query',
    label: 'Graph Query',
    scope: 'system',
  },
]

// The admin section shown when none is specified in the URL.
const DEFAULT_SECTION = SECTIONS[0]

// Sections that moved to the Agents area. Old links open the new page.
const MOVED_SECTIONS: Record<string, AgentsSection> = {
  'agent-runners': 'runners',
  'egress-destinations': 'egress',
}

// fallow-ignore-next-line complexity
export function Admin() {
  const navigate = useNavigate()
  const { action, section, slug } = useParams<{
    action?: string
    section?: string
    slug?: string
  }>()
  const isSubPage = !!slug
  const currentSectionData =
    SECTIONS.find((s) => s.id === section) ?? DEFAULT_SECTION
  const currentSection = currentSectionData.id
  const [isCollapsed, setIsCollapsed] = useState(false)
  const { selectedOrganization } = useOrganization()

  useEffect(() => {
    const moved = section ? MOVED_SECTIONS[section] : undefined
    if (moved) {
      const rest = [slug, action].filter((p): p is string => !!p)
      navigate(agentsPath(moved, ...rest), { replace: true })
    } else if (section === undefined) {
      navigate(`/admin/${DEFAULT_SECTION.id}`, { replace: true })
    }
  }, [action, section, slug, navigate])

  const orgName = selectedOrganization?.name || 'Organization'
  const Content = currentSectionData.component

  // fallow-ignore-next-line complexity
  const renderSectionButton = (sectionDef: SectionDef) => {
    const Icon = sectionDef.icon
    const isActive = currentSection === sectionDef.id
    return (
      <Button
        asChild
        className={`h-auto w-full items-start justify-start rounded-lg text-left transition-colors ${
          isCollapsed ? 'justify-center px-3 py-3' : 'px-4 py-3'
        } ${
          isActive
            ? 'bg-amber-bg text-amber-text hover:bg-amber-bg hover:text-amber-text'
            : 'text-secondary hover:bg-secondary hover:text-primary'
        }`}
        key={sectionDef.id}
        title={isCollapsed ? sectionDef.label : sectionDef.description}
        variant="ghost"
      >
        <Link to={`/admin/${sectionDef.id}`}>
          <Icon className="mt-0.5 size-5 shrink-0" />
          {!isCollapsed && (
            <>
              <div
                className={`min-w-0 flex-1 font-medium ${isActive ? 'text-amber-text' : ''}`}
              >
                {sectionDef.label}
              </div>
              {isActive && <ChevronRight className="mt-0.5 size-4 shrink-0" />}
            </>
          )}
        </Link>
      </Button>
    )
  }

  const renderScope = (
    scope: SectionDef['scope'],
    title: string,
    ScopeIcon: typeof Users,
  ) => {
    const sections = SECTIONS.filter((s) => s.scope === scope)
    const groups = [...new Set(sections.map((s) => s.group))]
    return (
      <div className="pb-6">
        {!isCollapsed && (
          <div className="text-tertiary flex items-center gap-2 px-3 pt-4 pb-2 text-xs tracking-wider uppercase">
            <ScopeIcon className="size-3" />
            {title}
          </div>
        )}
        {groups.map((group) => (
          <div className="space-y-1 pb-2" key={group}>
            {!isCollapsed && group && (
              <div className="text-tertiary px-4 pt-3 pb-1 text-xs font-medium">
                {group}
              </div>
            )}
            {sections.filter((s) => s.group === group).map(renderSectionButton)}
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="bg-tertiary text-primary min-h-screen">
      <div className="flex">
        {/* Side Navigation */}
        <aside
          className={`border-tertiary relative flex min-h-screen flex-col border-r transition-all duration-300 ${
            isCollapsed ? 'w-20' : 'w-72'
          } bg-primary`}
        >
          {/* Collapse Toggle */}
          <div
            className={`absolute z-10 ${isCollapsed ? 'left-1/2 -translate-x-1/2' : 'right-2'}`}
            style={{ top: '22px' }}
          >
            <Button
              className="text-secondary hover:bg-secondary hover:text-primary size-auto rounded-lg p-2 transition-colors"
              onClick={() => setIsCollapsed(!isCollapsed)}
              size="icon"
              title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              variant="ghost"
            >
              {isCollapsed ? (
                <ChevronRight className="size-5" />
              ) : (
                <ChevronLeft className="size-5" />
              )}
            </Button>
          </div>

          <nav
            className={`flex-1 overflow-y-auto px-4 pb-4 ${isCollapsed ? 'pt-14' : 'pt-4'}`}
          >
            {renderScope('org', orgName, Building2)}
            {renderScope('system', 'Global', Globe)}
          </nav>
        </aside>

        {/* Main Content */}
        <main className="flex-1">
          {/* Section Header */}
          <div className="border-tertiary bg-primary border-b">
            <div className="px-8 py-6">
              <div className="flex items-center gap-3">
                <currentSectionData.icon className="text-amber-text size-5" />
                {isSubPage ? (
                  <Button
                    asChild
                    className="hover:text-amber-text h-auto p-0 text-xl font-semibold no-underline hover:no-underline"
                    variant="link"
                  >
                    <Link to={`/admin/${currentSection}`}>
                      {currentSectionData.label}
                    </Link>
                  </Button>
                ) : (
                  <h1 className="text-primary text-xl font-semibold">
                    {currentSectionData.label}
                  </h1>
                )}
              </div>
            </div>
          </div>

          {/* Section Content */}
          <div className="p-8">
            {/* A new key resets the defaults form for each organization. */}
            <Content
              key={
                currentSection === 'default-settings'
                  ? `${currentSection}:${selectedOrganization?.slug}`
                  : currentSection
              }
            />
          </div>
        </main>
      </div>
    </div>
  )
}
