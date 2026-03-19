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
import { useOrganization } from '@/contexts/OrganizationContext'
import { useNavigate, useParams } from 'react-router-dom'

interface AdminProps {
  isDarkMode: boolean
}

type AdminSection =
  | 'teams'
  | 'environments'
  | 'project-types'
  | 'third-party-services'
  | 'link-definitions'
  | 'blueprints'
  | 'organizations'
  | 'users'
  | 'service-accounts'
  | 'roles'
  | 'oauth'

const VALID_SECTIONS: AdminSection[] = [
  'teams',
  'environments',
  'project-types',
  'third-party-services',
  'link-definitions',
  'blueprints',
  'organizations',
  'users',
  'service-accounts',
  'roles',
  'oauth',
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

export function Admin({ isDarkMode }: AdminProps) {
  const navigate = useNavigate()
  const { section } = useParams<{ section?: string }>()
  const currentSection: AdminSection = isValidSection(section)
    ? section
    : 'teams'
  const [isCollapsed, setIsCollapsed] = useState(false)
  const { selectedOrganization } = useOrganization()

  const orgName = selectedOrganization?.name || 'Organization'

  const orgAdminSections: SectionDef[] = [
    {
      id: 'teams',
      label: 'Teams',
      icon: UsersRound,
      description: 'Manage teams',
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
      id: 'project-types',
      label: 'Project Types',
      icon: FolderTree,
      description: 'Manage project types',
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
      id: 'link-definitions',
      label: 'Link Definitions',
      icon: Link2,
      description: 'Manage link definitions for projects',
      scope: 'org',
    },
    {
      id: 'blueprints',
      label: 'Blueprints',
      icon: FileJson,
      description: 'Configure metadata templates',
      scope: 'org',
    },
  ]

  const systemAdminSections: SectionDef[] = [
    {
      id: 'organizations',
      label: 'Organizations',
      icon: Building2,
      description: 'Manage organizational units and access',
      scope: 'system',
    },
    {
      id: 'users',
      label: 'User Management',
      icon: Users,
      description: 'Manage user accounts and administrators',
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
      id: 'roles',
      label: 'Roles',
      icon: Shield,
      description: 'Define roles and permission collections',
      scope: 'system',
    },
    {
      id: 'oauth',
      label: 'OAuth Providers',
      icon: ExternalLink,
      description: 'Configure SSO authentication providers',
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
            ? isDarkMode
              ? 'bg-blue-900 text-blue-300'
              : 'bg-blue-50 text-[#2A4DD0]'
            : isDarkMode
              ? 'text-gray-300 hover:bg-gray-700 hover:text-white'
              : 'text-gray-700 hover:bg-gray-100 hover:text-gray-900'
        }`}
        title={isCollapsed ? sectionDef.label : undefined}
      >
        <Icon className="mt-0.5 h-5 w-5 flex-shrink-0" />
        {!isCollapsed && (
          <>
            <div
              className={`min-w-0 flex-1 font-medium ${isActive ? (isDarkMode ? 'text-blue-300' : 'text-[#2A4DD0]') : ''}`}
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
    <div
      className={`min-h-screen ${isDarkMode ? 'bg-gray-900' : 'bg-slate-50'}`}
    >
      <div className="flex">
        {/* Side Navigation */}
        <aside
          className={`relative flex min-h-screen flex-col border-r transition-all duration-300 ${
            isCollapsed ? 'w-20' : 'w-72'
          } ${isDarkMode ? 'border-gray-700 bg-gray-800' : 'border-gray-200 bg-white'}`}
        >
          {/* Collapse Toggle */}
          <div
            className={`absolute z-10 ${isCollapsed ? 'left-1/2 -translate-x-1/2' : 'right-2'}`}
            style={{ top: '22px' }}
          >
            <button
              onClick={() => setIsCollapsed(!isCollapsed)}
              className={`rounded-lg p-2 transition-colors ${
                isDarkMode
                  ? 'text-gray-400 hover:bg-gray-700 hover:text-white'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
              }`}
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
                <div
                  className={`flex items-center gap-2 px-3 pb-6 pt-4 text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-500' : 'text-gray-400'
                  }`}
                >
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
                  className={`flex items-center gap-2 px-3 pb-3 text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-500' : 'text-gray-400'
                  }`}
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
          <div
            className={`border-b ${isDarkMode ? 'border-gray-700 bg-gray-800' : 'border-gray-200 bg-white'}`}
          >
            <div className="px-8 py-6">
              <div className="flex items-center gap-3">
                {currentSectionData && (
                  <currentSectionData.icon
                    className={`h-6 w-6 ${isDarkMode ? 'text-blue-400' : 'text-[#2A4DD0]'}`}
                  />
                )}
                <h1
                  className={`text-2xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                >
                  {currentSectionData?.label}
                </h1>
              </div>
            </div>
          </div>

          {/* Section Content */}
          <div className="p-8">
            {currentSection === 'teams' && (
              <TeamManagement isDarkMode={isDarkMode} />
            )}
            {currentSection === 'environments' && (
              <EnvironmentManagement isDarkMode={isDarkMode} />
            )}
            {currentSection === 'project-types' && (
              <ProjectTypeManagement isDarkMode={isDarkMode} />
            )}
            {currentSection === 'third-party-services' && (
              <ThirdPartyServiceManagement isDarkMode={isDarkMode} />
            )}
            {currentSection === 'link-definitions' && (
              <LinkDefinitionManagement isDarkMode={isDarkMode} />
            )}
            {currentSection === 'blueprints' && (
              <BlueprintManagement isDarkMode={isDarkMode} />
            )}
            {currentSection === 'organizations' && (
              <OrganizationManagement isDarkMode={isDarkMode} />
            )}
            {currentSection === 'users' && (
              <UserManagement isDarkMode={isDarkMode} />
            )}
            {currentSection === 'service-accounts' && (
              <ServiceAccountManagement isDarkMode={isDarkMode} />
            )}
            {currentSection === 'roles' && (
              <RoleManagement isDarkMode={isDarkMode} />
            )}
            {currentSection === 'oauth' && (
              <OAuthManagement isDarkMode={isDarkMode} />
            )}
          </div>
        </main>
      </div>
    </div>
  )
}
