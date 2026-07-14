import { useEffect, useState } from 'react'

import { Link, useNavigate, useParams } from 'react-router-dom'

import {
  Blocks,
  Bot,
  Building2,
  ChevronLeft,
  ChevronRight,
  FileJson,
  FolderTree,
  Globe,
  History,
  KeyRound,
  Layers,
  LayoutDashboard,
  Link2,
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

import { Button } from '@/components/ui/button'
import { useOrganization } from '@/contexts/OrganizationContext'

import { AdminOverview } from './admin/AdminOverview'
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
import { ScoringPolicyManagement } from './admin/ScoringPolicyManagement'
import { ServiceAccountManagement } from './admin/ServiceAccountManagement'
import { TeamManagement } from './admin/TeamManagement'
import { UserManagement } from './admin/UserManagement'
import { WebhookHistory } from './admin/WebhookHistory'
import { WebhookManagement } from './admin/WebhookManagement'

type AdminSection =
  | 'assistant'
  | 'blueprints'
  | 'default-settings'
  | 'document-templates'
  | 'environments'
  | 'graph-query'
  | 'integrations'
  | 'link-definitions'
  | 'maintenance'
  | 'oauth'
  | 'organizations'
  | 'overview'
  | 'plugins'
  | 'project-types'
  | 'roles'
  | 'scoring-policies'
  | 'service-accounts'
  | 'teams'
  | 'users'
  | 'webhook-history'
  | 'webhooks'

// The admin section shown when none is specified in the URL.
const DEFAULT_ADMIN_SECTION: AdminSection = 'overview'

const VALID_SECTIONS: AdminSection[] = [
  'assistant',
  'blueprints',
  'default-settings',
  'environments',
  'graph-query',
  'integrations',
  'link-definitions',
  'document-templates',
  'maintenance',
  'oauth',
  'organizations',
  'overview',
  'plugins',
  'project-types',
  'roles',
  'scoring-policies',
  'service-accounts',
  'teams',
  'users',
  'webhook-history',
  'webhooks',
]

interface SectionDef {
  description: string
  icon: typeof Users
  id: AdminSection
  label: string
  scope: 'org' | 'system'
}

// fallow-ignore-next-line complexity
export function Admin() {
  const navigate = useNavigate()
  const { section, slug } = useParams<{ section?: string; slug?: string }>()
  const isSubPage = !!slug
  const currentSection: AdminSection = isValidSection(section)
    ? section
    : DEFAULT_ADMIN_SECTION
  const [isCollapsed, setIsCollapsed] = useState(false)
  const { selectedOrganization } = useOrganization()

  useEffect(() => {
    if (section === undefined) {
      navigate(`/admin/${DEFAULT_ADMIN_SECTION}`, { replace: true })
    }
  }, [section, navigate])

  const orgName = selectedOrganization?.name || 'Organization'

  const orgAdminSections: SectionDef[] = [
    {
      description: 'Operations metrics and system health at a glance',
      icon: LayoutDashboard,
      id: 'overview',
      label: 'Overview',
      scope: 'org',
    },
    {
      description: 'Configure metadata templates',
      icon: FileJson,
      id: 'blueprints',
      label: 'Blueprints',
      scope: 'org',
    },
    {
      description: 'Organization-wide defaults, including version formats',
      icon: SlidersHorizontal,
      id: 'default-settings',
      label: 'Default Settings',
      scope: 'org',
    },
    {
      description: 'Manage reusable document templates',
      icon: StickyNote,
      id: 'document-templates',
      label: 'Document Templates',
      scope: 'org',
    },
    {
      description: 'Manage environments',
      icon: Layers,
      id: 'environments',
      label: 'Environments',
      scope: 'org',
    },
    {
      description: 'Connect external platforms',
      icon: Blocks,
      id: 'integrations',
      label: 'Integrations',
      scope: 'org',
    },
    {
      description: 'Manage link definitions for projects',
      icon: Link2,
      id: 'link-definitions',
      label: 'Link Definitions',
      scope: 'org',
    },
    {
      description: 'Manage project types',
      icon: FolderTree,
      id: 'project-types',
      label: 'Project Types',
      scope: 'org',
    },
    {
      description:
        'Define attribute, presence, link, and age-based scoring policies',
      icon: Target,
      id: 'scoring-policies',
      label: 'Scoring Policies',
      scope: 'org',
    },
    {
      description: 'Manage teams',
      icon: UsersRound,
      id: 'teams',
      label: 'Teams',
      scope: 'org',
    },
    {
      description:
        'Browse recent inbound webhook deliveries and dispatch outcomes',
      icon: History,
      id: 'webhook-history',
      label: 'Webhook History',
      scope: 'org',
    },
    {
      description: 'Configure inbound webhook processing',
      icon: Webhook,
      id: 'webhooks',
      label: 'Webhooks',
      scope: 'org',
    },
  ]

  const systemAdminSections: SectionDef[] = [
    {
      description: 'Configure the AI assistant and its MCP servers',
      icon: Sparkles,
      id: 'assistant',
      label: 'Assistant',
      scope: 'system',
    },
    {
      description: 'Configure SSO authentication providers',
      icon: KeyRound,
      id: 'oauth',
      label: 'Auth Providers',
      scope: 'system',
    },
    {
      description: 'Run ad-hoc Cypher queries against the graph database',
      icon: Network,
      id: 'graph-query',
      label: 'Graph Query',
      scope: 'system',
    },
    {
      description: 'Run global background maintenance operations',
      icon: Wrench,
      id: 'maintenance',
      label: 'Maintenance',
      scope: 'system',
    },
    {
      description: 'Manage organizational units and access',
      icon: Building2,
      id: 'organizations',
      label: 'Organizations',
      scope: 'system',
    },
    {
      description: 'Manage installed plugins',
      icon: Puzzle,
      id: 'plugins',
      label: 'Plugins',
      scope: 'system',
    },
    {
      description: 'Define roles and permission collections',
      icon: Shield,
      id: 'roles',
      label: 'Roles',
      scope: 'system',
    },
    {
      description: 'Manage service accounts and API keys',
      icon: Bot,
      id: 'service-accounts',
      label: 'Service Accounts',
      scope: 'system',
    },
    {
      description: 'Manage user accounts and administrators',
      icon: Users,
      id: 'users',
      label: 'User Management',
      scope: 'system',
    },
  ]

  const allSections = [...orgAdminSections, ...systemAdminSections]
  const currentSectionData = allSections.find((s) => s.id === currentSection)

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
        title={isCollapsed ? sectionDef.label : undefined}
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
            className={`flex-1 space-y-1 overflow-y-auto px-4 pb-4 ${isCollapsed ? 'pt-14' : 'pt-4'}`}
          >
            {/* Organization Scope Section */}
            <div style={{ paddingBottom: '2em' }}>
              {!isCollapsed && (
                <div className="text-tertiary flex items-center gap-2 px-3 pt-4 pb-6 text-xs tracking-wider uppercase">
                  <Building2 className="size-3" />
                  {orgName} Admin
                </div>
              )}
              {orgAdminSections.map(renderSectionButton)}
            </div>

            {/* System Admin Section */}
            <div>
              {!isCollapsed && (
                <div
                  className="text-tertiary flex items-center gap-2 px-3 pb-3 text-xs tracking-wider uppercase"
                  style={{ paddingTop: '2em' }}
                >
                  <Globe className="size-3" />
                  Global Admin
                </div>
              )}
              {systemAdminSections.map(renderSectionButton)}
            </div>
          </nav>
        </aside>

        {/* Main Content */}
        <main className="flex-1">
          {/* Section Header */}
          <div className="border-tertiary bg-primary border-b">
            <div className="px-8 py-6">
              <div className="flex items-center gap-3">
                {currentSectionData && (
                  <currentSectionData.icon className="text-amber-text size-5" />
                )}
                {isSubPage ? (
                  <Button
                    asChild
                    className="hover:text-amber-text h-auto p-0 text-xl font-semibold no-underline hover:no-underline"
                    variant="link"
                  >
                    <Link to={`/admin/${currentSection}`}>
                      {currentSectionData?.label}
                    </Link>
                  </Button>
                ) : (
                  <h1 className="text-primary text-xl font-semibold">
                    {currentSectionData?.label}
                  </h1>
                )}
              </div>
            </div>
          </div>

          {/* Section Content */}
          <div className="p-8">
            {currentSection === 'overview' && <AdminOverview />}
            {currentSection === 'default-settings' && (
              <DefaultSettingsManagement key={selectedOrganization?.slug} />
            )}
            {currentSection === 'teams' && <TeamManagement />}
            {currentSection === 'environments' && <EnvironmentManagement />}
            {currentSection === 'project-types' && <ProjectTypeManagement />}
            {currentSection === 'integrations' && <IntegrationsManagement />}
            {currentSection === 'webhooks' && <WebhookManagement />}
            {currentSection === 'webhook-history' && (
              <WebhookHistory eventId={slug} />
            )}
            {currentSection === 'link-definitions' && (
              <LinkDefinitionManagement />
            )}
            {currentSection === 'document-templates' && (
              <DocumentTemplateManagement />
            )}
            {currentSection === 'blueprints' && <BlueprintManagement />}
            {currentSection === 'organizations' && <OrganizationManagement />}
            {currentSection === 'users' && <UserManagement />}
            {currentSection === 'service-accounts' && (
              <ServiceAccountManagement />
            )}
            {currentSection === 'roles' && <RoleManagement />}
            {currentSection === 'scoring-policies' && (
              <ScoringPolicyManagement />
            )}
            {currentSection === 'assistant' && <AssistantManagement />}
            {currentSection === 'oauth' && <AuthProvidersManagement />}
            {currentSection === 'graph-query' && <GraphQueryManagement />}
            {currentSection === 'maintenance' && <MaintenanceManagement />}
            {currentSection === 'plugins' && <PluginsManagement />}
          </div>
        </main>
      </div>
    </div>
  )
}

function isValidSection(value: string | undefined): value is AdminSection {
  return VALID_SECTIONS.includes(value as AdminSection)
}
