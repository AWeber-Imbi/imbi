import { useState } from 'react'
import {
  Users,
  Shield,
  FileJson,
  ChevronRight,
  ChevronLeft,
  ExternalLink,
  Building2,
  Globe,
  Layers,
  FolderTree,
  UsersRound,
  Bot,
  Cloud,
  Link2,
  Webhook,
} from 'lucide-react'
import { UserManagement } from './admin/UserManagement'
import { RoleManagement } from './admin/RoleManagement'
import { BlueprintManagement } from './admin/BlueprintManagement'
import { OrganizationManagement } from './admin/OrganizationManagement'
import { TeamManagement } from './admin/TeamManagement'
import { ServiceAccountManagement } from './admin/ServiceAccountManagement'
import { OAuthManagement } from './admin/OAuthManagement'
import { EnvironmentManagement } from './admin/EnvironmentManagement'
import { ProjectTypeManagement } from './admin/ProjectTypeManagement'
import { ThirdPartyServiceManagement } from './admin/ThirdPartyServiceManagement'
import { LinkDefinitionManagement } from './admin/LinkDefinitionManagement'
import { WebhookManagement } from './admin/WebhookManagement'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useNavigate, useParams } from 'react-router-dom'

type AdminSection =
  | 'teams'
  | 'environments'
  | 'project-types'
  | 'third-party-services'
  | 'webhooks'
  | 'link-definitions'
  | 'blueprints'
  | 'organizations'
  | 'users'
  | 'service-accounts'
  | 'roles'
  | 'oauth'

const VALID_SECTIONS: AdminSection[] = [
  'blueprints',
  'environments',
  'link-definitions',
  'oauth',
  'organizations',
  'project-types',
  'roles',
  'service-accounts',
  'teams',
  'third-party-services',
  'users',
  'webhooks',
]

function isValidSection(value: string | undefined): value is AdminSection {
  return VALID_SECTIONS.includes(value as AdminSection)
}

interface SectionDef {
  id: AdminSection
  label: string
  icon: typeof Users
  description: string
  scope: 'org' | 'system'
}

export function Admin() {
  const navigate = useNavigate()
  const { section } = useParams<{ section?: string }>()
  const currentSection: AdminSection = isValidSection(section)
    ? section
    : 'blueprints'
  const [isCollapsed, setIsCollapsed] = useState(false)
  const { selectedOrganization } = useOrganization()

  const orgName = selectedOrganization?.name || 'Organization'

  const orgAdminSections: SectionDef[] = [
    {
      id: 'blueprints',
      label: 'Blueprints',
      icon: FileJson,
      description: 'Configure metadata templates',
      scope: 'org',
    },
    {
      id: 'environments',
      label: 'Environments',
      icon: Layers,
      description: 'Manage environments',
      scope: 'org',
    },
    {
      id: 'link-definitions',
      label: 'Link Definitions',
      icon: Link2,
      description: 'Manage link definitions for projects',
      scope: 'org',
    },
    {
      id: 'project-types',
      label: 'Project Types',
      icon: FolderTree,
      description: 'Manage project types',
      scope: 'org',
    },
    {
      id: 'teams',
      label: 'Teams',
      icon: UsersRound,
      description: 'Manage teams',
      scope: 'org',
    },
    {
      id: 'third-party-services',
      label: 'Third-Party Services',
      icon: Cloud,
      description: 'Manage external SaaS services',
      scope: 'org',
    },
    {
      id: 'webhooks',
      label: 'Webhooks',
      icon: Webhook,
      description: 'Configure inbound webhook processing',
      scope: 'org',
    },
  ]

  const systemAdminSections: SectionDef[] = [
    {
      id: 'oauth',
      label: 'OAuth Providers',
      icon: ExternalLink,
      description: 'Configure SSO authentication providers',
      scope: 'system',
    },
    {
      id: 'organizations',
      label: 'Organizations',
      icon: Building2,
      description: 'Manage organizational units and access',
      scope: 'system',
    },
    {
      id: 'roles',
      label: 'Roles',
      icon: Shield,
      description: 'Define roles and permission collections',
      scope: 'system',
    },
    {
      id: 'service-accounts',
      label: 'Service Accounts',
      icon: Bot,
      description: 'Manage service accounts and API keys',
      scope: 'system',
    },
    {
      id: 'users',
      label: 'User Management',
      icon: Users,
      description: 'Manage user accounts and administrators',
      scope: 'system',
    },
  ]

  const allSections = [...orgAdminSections, ...systemAdminSections]
  const currentSectionData = allSections.find((s) => s.id === currentSection)

  const renderSectionButton = (sectionDef: SectionDef) => {
    const Icon = sectionDef.icon
    const isActive = currentSection === sectionDef.id
    return (
      <button
        key={sectionDef.id}
        onClick={() => navigate(`/admin/${sectionDef.id}`)}
        className={`flex w-full items-start gap-3 rounded-lg text-left transition-colors ${
          isCollapsed ? 'justify-center px-3 py-3' : 'px-4 py-3'
        } ${
          isActive
            ? 'bg-amber-bg text-amber-text'
            : 'text-secondary hover:bg-secondary hover:text-primary'
        }`}
        title={isCollapsed ? sectionDef.label : undefined}
      >
        <Icon className="mt-0.5 h-5 w-5 flex-shrink-0" />
        {!isCollapsed && (
          <>
            <div
              className={`min-w-0 flex-1 font-medium ${isActive ? 'text-amber-text' : ''}`}
            >
              {sectionDef.label}
            </div>
            {isActive && (
              <ChevronRight className="mt-0.5 h-4 w-4 flex-shrink-0" />
            )}
          </>
        )}
      </button>
    )
  }

  return (
    <div className="min-h-screen bg-tertiary text-primary">
      <div className="flex">
        {/* Side Navigation */}
        <aside
          className={`relative flex min-h-screen flex-col border-r border-tertiary transition-all duration-300 ${
            isCollapsed ? 'w-20' : 'w-72'
          } bg-primary`}
        >
          {/* Collapse Toggle */}
          <div
            className={`absolute z-10 ${isCollapsed ? 'left-1/2 -translate-x-1/2' : 'right-2'}`}
            style={{ top: '22px' }}
          >
            <button
              onClick={() => setIsCollapsed(!isCollapsed)}
              className="rounded-lg p-2 text-secondary transition-colors hover:bg-secondary hover:text-primary"
              title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              {isCollapsed ? (
                <ChevronRight className="h-5 w-5" />
              ) : (
                <ChevronLeft className="h-5 w-5" />
              )}
            </button>
          </div>

          <nav
            className={`flex-1 space-y-1 overflow-y-auto px-4 pb-4 ${isCollapsed ? 'pt-14' : 'pt-4'}`}
          >
            {/* Organization Scope Section */}
            <div style={{ paddingBottom: '2em' }}>
              {!isCollapsed && (
                <div className="flex items-center gap-2 px-3 pb-6 pt-4 text-xs uppercase tracking-wider text-tertiary">
                  <Building2 className="h-3 w-3" />
                  {orgName} Admin
                </div>
              )}
              {orgAdminSections.map(renderSectionButton)}
            </div>

            {/* System Admin Section */}
            <div>
              {!isCollapsed && (
                <div
                  className="flex items-center gap-2 px-3 pb-3 text-xs uppercase tracking-wider text-tertiary"
                  style={{ paddingTop: '2em' }}
                >
                  <Globe className="h-3 w-3" />
                  System Admin
                </div>
              )}
              {systemAdminSections.map(renderSectionButton)}
            </div>
          </nav>
        </aside>

        {/* Main Content */}
        <main className="flex-1">
          {/* Section Header */}
          <div className="border-b border-tertiary bg-primary">
            <div className="px-8 py-6">
              <div className="flex items-center gap-3">
                {currentSectionData && (
                  <currentSectionData.icon className="h-5 w-5 text-amber-text" />
                )}
                <h1 className="text-xl font-semibold text-primary">
                  {currentSectionData?.label}
                </h1>
              </div>
            </div>
          </div>

          {/* Section Content */}
          <div className="p-8">
            {currentSection === 'teams' && <TeamManagement />}
            {currentSection === 'environments' && <EnvironmentManagement />}
            {currentSection === 'project-types' && <ProjectTypeManagement />}
            {currentSection === 'third-party-services' && (
              <ThirdPartyServiceManagement />
            )}
            {currentSection === 'webhooks' && <WebhookManagement />}
            {currentSection === 'link-definitions' && (
              <LinkDefinitionManagement />
            )}
            {currentSection === 'blueprints' && <BlueprintManagement />}
            {currentSection === 'organizations' && <OrganizationManagement />}
            {currentSection === 'users' && <UserManagement />}
            {currentSection === 'service-accounts' && (
              <ServiceAccountManagement />
            )}
            {currentSection === 'roles' && <RoleManagement />}
            {currentSection === 'oauth' && <OAuthManagement />}
          </div>
        </main>
      </div>
    </div>
  )
}
