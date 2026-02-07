import { useState } from 'react'
import {
  Users, Shield, FileJson, ChevronRight, ChevronLeft,
  ExternalLink, Building2, Globe, Layers, FolderTree, UsersRound, Bot,
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
import { useOrganization } from '@/contexts/OrganizationContext'
import { useNavigate, useParams } from 'react-router-dom'

interface AdminProps {
  isDarkMode: boolean
}

type AdminSection =
  | 'teams'
  | 'environments'
  | 'project-types'
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
  const currentSection: AdminSection = isValidSection(section) ? section : 'teams'
  const [isCollapsed, setIsCollapsed] = useState(false)
  const { selectedOrganization } = useOrganization()

  const orgName = selectedOrganization?.name || 'Organization'

  const orgAdminSections: SectionDef[] = [
    { id: 'teams', label: 'Teams', icon: UsersRound, description: `Manage teams in ${orgName}`, scope: 'org' },
    { id: 'environments', label: 'Environments', icon: Layers, description: `Manage environments in ${orgName}`, scope: 'org' },
    { id: 'project-types', label: 'Project Types', icon: FolderTree, description: `Manage project types in ${orgName}`, scope: 'org' },
    { id: 'blueprints', label: 'Blueprints', icon: FileJson, description: `Configure metadata templates in ${orgName}`, scope: 'org' },
  ]

  const systemAdminSections: SectionDef[] = [
    { id: 'organizations', label: 'Organizations', icon: Building2, description: 'Manage organizational units and access', scope: 'system' },
    { id: 'users', label: 'User Management', icon: Users, description: 'Manage user accounts and administrators', scope: 'system' },
    { id: 'service-accounts', label: 'Service Accounts', icon: Bot, description: 'Manage service accounts and API keys', scope: 'system' },
    { id: 'roles', label: 'Roles', icon: Shield, description: 'Define roles and permission collections', scope: 'system' },
    { id: 'oauth', label: 'OAuth Providers', icon: ExternalLink, description: 'Configure SSO authentication providers', scope: 'system' },
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
        className={`w-full flex items-start gap-3 rounded-lg transition-colors text-left ${
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
        <Icon className="w-5 h-5 mt-0.5 flex-shrink-0" />
        {!isCollapsed && (
          <>
            <div className="flex-1 min-w-0">
              <div className={`font-medium ${isActive ? (isDarkMode ? 'text-blue-300' : 'text-[#2A4DD0]') : ''}`}>
                {sectionDef.label}
              </div>
              <div className={`text-xs mt-0.5 ${
                isActive
                  ? isDarkMode ? 'text-blue-400/70' : 'text-[#2A4DD0]/70'
                  : isDarkMode ? 'text-gray-500' : 'text-gray-500'
              }`}>
                {sectionDef.description}
              </div>
            </div>
            {isActive && <ChevronRight className="w-4 h-4 mt-1 flex-shrink-0" />}
          </>
        )}
      </button>
    )
  }

  return (
    <div className={`min-h-screen ${isDarkMode ? 'bg-gray-900' : 'bg-slate-50'}`}>
      <div className="flex">
        {/* Side Navigation */}
        <aside className={`min-h-screen border-r flex flex-col transition-all duration-300 relative ${
          isCollapsed ? 'w-20' : 'w-72'
        } ${isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'}`}>

          {/* Collapse Toggle */}
          <div className={`absolute z-10 ${isCollapsed ? 'left-1/2 -translate-x-1/2' : 'right-2'}`} style={{ top: '22px' }}>
            <button
              onClick={() => setIsCollapsed(!isCollapsed)}
              className={`p-2 rounded-lg transition-colors ${
                isDarkMode
                  ? 'text-gray-400 hover:bg-gray-700 hover:text-white'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
              }`}
              title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              {isCollapsed ? (
                <ChevronRight className="w-5 h-5" />
              ) : (
                <ChevronLeft className="w-5 h-5" />
              )}
            </button>
          </div>

          <nav className={`px-4 pb-4 space-y-1 flex-1 overflow-y-auto ${isCollapsed ? 'pt-14' : 'pt-4'}`}>
            {/* Organization Scope Section */}
            <div style={{ paddingBottom: '2em' }}>
              {!isCollapsed && (
                <div className={`px-3 pt-4 pb-6 text-xs uppercase tracking-wider flex items-center gap-2 ${
                  isDarkMode ? 'text-gray-500' : 'text-gray-400'
                }`}>
                  <Building2 className="w-3 h-3" />
                  {orgName} Admin
                </div>
              )}
              {orgAdminSections.map(renderSectionButton)}
            </div>

            {/* System Admin Section */}
            <div>
              {!isCollapsed && (
                <div className={`px-3 pb-3 text-xs uppercase tracking-wider flex items-center gap-2 ${
                  isDarkMode ? 'text-gray-500' : 'text-gray-400'
                }`} style={{ paddingTop: '2em' }}>
                  <Globe className="w-3 h-3" />
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
          <div className={`border-b ${isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'}`}>
            <div className="px-8 py-6">
              <div className="flex items-center gap-3">
                {currentSectionData && <currentSectionData.icon className={`w-6 h-6 ${isDarkMode ? 'text-blue-400' : 'text-[#2A4DD0]'}`} />}
                <div>
                  <div className="flex items-center gap-3">
                    <h1 className={`text-2xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                      {currentSectionData?.label}
                    </h1>
                    {currentSectionData?.scope === 'org' && selectedOrganization && (
                      <span className={`px-2 py-1 rounded-full text-xs ${
                        isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-700'
                      }`}>
                        {selectedOrganization.name} only
                      </span>
                    )}
                  </div>
                  <p className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                    {currentSectionData?.description}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Section Content */}
          <div className="p-8">
            {currentSection === 'teams' && <TeamManagement isDarkMode={isDarkMode} />}
            {currentSection === 'environments' && <EnvironmentManagement isDarkMode={isDarkMode} />}
            {currentSection === 'project-types' && <ProjectTypeManagement isDarkMode={isDarkMode} />}
            {currentSection === 'blueprints' && <BlueprintManagement isDarkMode={isDarkMode} />}
            {currentSection === 'organizations' && <OrganizationManagement isDarkMode={isDarkMode} />}
            {currentSection === 'users' && <UserManagement isDarkMode={isDarkMode} />}
            {currentSection === 'service-accounts' && <ServiceAccountManagement isDarkMode={isDarkMode} />}
            {currentSection === 'roles' && <RoleManagement isDarkMode={isDarkMode} />}
            {currentSection === 'oauth' && <OAuthManagement isDarkMode={isDarkMode} />}
          </div>
        </main>
      </div>
    </div>
  )
}
