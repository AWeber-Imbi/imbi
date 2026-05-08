import { useEffect, useState } from 'react'

import { useNavigate, useParams } from 'react-router-dom'

import {
  Bot,
  Building2,
  ChevronLeft,
  ChevronRight,
  Cloud,
  FileJson,
  FolderTree,
  Globe,
  KeyRound,
  Layers,
  Link2,
  Puzzle,
  Shield,
  StickyNote,
  Target,
  Users,
  UsersRound,
  Webhook,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useOrganization } from '@/contexts/OrganizationContext'

import { AuthProvidersManagement } from './admin/AuthProvidersManagement'
import { BlueprintManagement } from './admin/BlueprintManagement'
import { DocumentTemplateManagement } from './admin/DocumentTemplateManagement'
import { EnvironmentManagement } from './admin/EnvironmentManagement'
import { LinkDefinitionManagement } from './admin/LinkDefinitionManagement'
import { OrganizationManagement } from './admin/OrganizationManagement'
import { PluginPackageDetail } from './admin/PluginPackageDetail'
import { PluginsManagement } from './admin/PluginsManagement'
import { ProjectTypeManagement } from './admin/ProjectTypeManagement'
import { RoleManagement } from './admin/RoleManagement'
import { ScoringPolicyManagement } from './admin/ScoringPolicyManagement'
import { ServiceAccountManagement } from './admin/ServiceAccountManagement'
import { TeamManagement } from './admin/TeamManagement'
import { ThirdPartyServiceManagement } from './admin/ThirdPartyServiceManagement'
import { UserManagement } from './admin/UserManagement'
import { WebhookManagement } from './admin/WebhookManagement'

type AdminSection =
  | 'blueprints'
  | 'document-templates'
  | 'environments'
  | 'link-definitions'
  | 'oauth'
  | 'organizations'
  | 'plugins'
  | 'project-types'
  | 'roles'
  | 'scoring-policies'
  | 'service-accounts'
  | 'teams'
  | 'third-party-services'
  | 'users'
  | 'webhooks'

const VALID_SECTIONS: AdminSection[] = [
  'blueprints',
  'environments',
  'link-definitions',
  'document-templates',
  'oauth',
  'organizations',
  'plugins',
  'project-types',
  'roles',
  'scoring-policies',
  'service-accounts',
  'teams',
  'third-party-services',
  'users',
  'webhooks',
]

interface SectionDef {
  description: string
  icon: typeof Users
  id: AdminSection
  label: string
  scope: 'org' | 'system'
}

export function Admin() {
  const navigate = useNavigate()
  const { section, slug } = useParams<{ section?: string; slug?: string }>()
  const isSubPage = !!slug
  const currentSection: AdminSection = isValidSection(section)
    ? section
    : 'blueprints'
  const [isCollapsed, setIsCollapsed] = useState(false)
  const { selectedOrganization } = useOrganization()

  useEffect(() => {
    if (section === undefined) {
      navigate('/admin/blueprints', { replace: true })
    }
  }, [section, navigate])

  const orgName = selectedOrganization?.name || 'Organization'

  const orgAdminSections: SectionDef[] = [
    {
      description: 'Configure metadata templates',
      icon: FileJson,
      id: 'blueprints',
      label: 'Blueprints',
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
      description: 'Manage link definitions for projects',
      icon: Link2,
      id: 'link-definitions',
      label: 'Link Definitions',
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
      description: 'Manage project types',
      icon: FolderTree,
      id: 'project-types',
      label: 'Project Types',
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
      description: 'Define attribute-based project scoring policies',
      icon: Target,
      id: 'scoring-policies',
      label: 'Scoring Policies',
      scope: 'org',
    },
    {
      description: 'Manage external SaaS services',
      icon: Cloud,
      id: 'third-party-services',
      label: 'Third-Party Services',
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
      description: 'Manage organizational units and access',
      icon: Building2,
      id: 'organizations',
      label: 'Organizations',
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

  const renderSectionButton = (sectionDef: SectionDef) => {
    const Icon = sectionDef.icon
    const isActive = currentSection === sectionDef.id
    return (
      <Button
        className={`h-auto w-full items-start justify-start rounded-lg text-left transition-colors ${
          isCollapsed ? 'justify-center px-3 py-3' : 'px-4 py-3'
        } ${
          isActive
            ? 'bg-amber-bg text-amber-text hover:bg-amber-bg hover:text-amber-text'
            : 'text-secondary hover:bg-secondary hover:text-primary'
        }`}
        key={sectionDef.id}
        onClick={() => navigate(`/admin/${sectionDef.id}`)}
        title={isCollapsed ? sectionDef.label : undefined}
        variant="ghost"
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
      </Button>
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
            <Button
              className="h-auto w-auto rounded-lg p-2 text-secondary transition-colors hover:bg-secondary hover:text-primary"
              onClick={() => setIsCollapsed(!isCollapsed)}
              size="icon"
              title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              variant="ghost"
            >
              {isCollapsed ? (
                <ChevronRight className="h-5 w-5" />
              ) : (
                <ChevronLeft className="h-5 w-5" />
              )}
            </Button>
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
          <div className="border-b border-tertiary bg-primary">
            <div className="px-8 py-6">
              <div className="flex items-center gap-3">
                {currentSectionData && (
                  <currentSectionData.icon className="h-5 w-5 text-amber-text" />
                )}
                {isSubPage ? (
                  <button
                    className="text-xl font-semibold text-primary hover:text-amber-text"
                    onClick={() => navigate(`/admin/${currentSection}`)}
                    type="button"
                  >
                    {currentSectionData?.label}
                  </button>
                ) : (
                  <h1 className="text-xl font-semibold text-primary">
                    {currentSectionData?.label}
                  </h1>
                )}
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
            {currentSection === 'oauth' && <AuthProvidersManagement />}
            {currentSection === 'plugins' && !slug && <PluginsManagement />}
            {currentSection === 'plugins' && slug && (
              <PluginPackageDetail
                onBack={() => navigate('/admin/plugins')}
                slug={slug}
              />
            )}
          </div>
        </main>
      </div>
    </div>
  )
}

function isValidSection(value: string | undefined): value is AdminSection {
  return VALID_SECTIONS.includes(value as AdminSection)
}
