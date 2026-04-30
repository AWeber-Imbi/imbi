import { useMemo } from 'react'

import { useLocation, useNavigate } from 'react-router-dom'

import {
  Activity,
  BarChart3,
  Building2,
  ChevronDown,
  FolderKanban,
  LogOut,
  Moon,
  Plus,
  Rocket,
  Settings,
  Sun,
  User,
  UserCircle,
} from 'lucide-react'

import logoDark from '@/assets/logo-dark.svg'
import logoLight from '@/assets/logo-light.svg'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useTheme } from '@/contexts/ThemeContext'
import { useAuth } from '@/hooks/useAuth'
import { useIcon } from '@/lib/icons'
import type { Organization } from '@/types'
import { UserResponse } from '@/types'

import { Button } from './ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from './ui/dropdown-menu'
import { Gravatar } from './ui/gravatar'

interface NavigationProps {
  currentView?: string
  onNewDeployment?: () => void
  onNewOpsEntry?: () => void
  onNewProject?: () => void
  onViewChange?: (view: string) => void
}

export function Navigation({
  currentView,
  onNewDeployment,
  onNewOpsEntry,
  onNewProject,
  onViewChange,
}: NavigationProps) {
  const { isDarkMode, toggleTheme } = useTheme()
  const { logout, user } = useAuth()
  const { organizations, selectedOrganization, setSelectedOrganization } =
    useOrganization()
  const navigate = useNavigate()
  const location = useLocation()

  // Check if user is admin (safely cast to UserResponse to access is_admin)
  const isAdmin = (user as null | UserResponse)?.is_admin === true

  // Memoize navItems to avoid array mutation on every render
  const navItems = useMemo(() => {
    const items = [
      {
        icon: FolderKanban,
        id: 'projects',
        label: 'Projects',
        path: '/projects',
      },
      {
        icon: Rocket,
        id: 'deployments',
        label: 'Deployments',
        path: '/deployments',
      },
      {
        icon: Activity,
        id: 'operations',
        label: 'Operations Log',
        path: '/operations-log',
      },
      { icon: BarChart3, id: 'reports', label: 'Reports', path: '/reports' },
    ]

    // Add Admin nav item if user is admin
    if (isAdmin) {
      items.push({
        icon: Settings,
        id: 'admin',
        label: 'Admin',
        path: '/admin',
      })
    }

    return items
  }, [isAdmin])

  // Determine active view from route if not explicitly provided
  const activeView =
    currentView ||
    navItems.find((item) => location.pathname === item.path)?.id ||
    'dashboard'

  return (
    <nav className="fixed left-0 right-0 top-0 z-50 border-b border-tertiary bg-primary transition-colors">
      <div className="flex h-16 items-center justify-between px-6">
        {/* Logo and Brand */}
        <div className="flex items-center gap-8">
          <Button
            className="h-auto rounded-lg px-2 py-1.5 transition-all hover:bg-secondary"
            onClick={() => navigate('/dashboard')}
            variant="ghost"
          >
            <img
              alt="Imbi"
              className="h-8 w-8"
              src={isDarkMode ? logoDark : logoLight}
            />
            <span className="text-primary" style={{ fontWeight: 800 }}>
              Imbi
            </span>
          </Button>

          {/* Navigation Items */}
          <div className="hidden items-center gap-1 md:flex">
            {navItems.map((item) => {
              const Icon = item.icon
              const isActive = activeView === item.id
              return (
                <Button
                  className={`h-auto rounded-lg px-4 py-2 transition-colors ${
                    isActive
                      ? 'bg-amber-bg text-amber-text hover:bg-amber-bg hover:text-amber-text'
                      : 'text-secondary hover:bg-secondary hover:text-primary'
                  }`}
                  key={item.id}
                  onClick={() => navigate(item.path)}
                  variant="ghost"
                >
                  <Icon className="h-4 w-4" />
                  <span>{item.label}</span>
                </Button>
              )
            })}
          </div>
        </div>

        {/* Right Side Actions */}
        <div className="flex items-center gap-3">
          {/* Organization Selector */}
          {organizations.length > 0 &&
            selectedOrganization &&
            (organizations.length === 1 ? (
              <Button
                className="pointer-events-none max-w-[200px] cursor-default gap-2 border-tertiary bg-primary text-primary"
                size="sm"
                variant="outline"
              >
                <OrgIcon
                  className="h-4 w-4 flex-shrink-0 rounded object-cover"
                  org={selectedOrganization}
                />
                <span className="truncate">{selectedOrganization.name}</span>
              </Button>
            ) : (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    className="max-w-[200px] gap-2 border-tertiary bg-primary text-primary hover:bg-secondary"
                    size="sm"
                    variant="outline"
                  >
                    <OrgIcon
                      className="h-4 w-4 flex-shrink-0 rounded object-cover"
                      org={selectedOrganization}
                    />
                    <span className="truncate">
                      {selectedOrganization.name}
                    </span>
                    <ChevronDown className="h-3 w-3 flex-shrink-0" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-56">
                  {organizations.map((org) => (
                    <DropdownMenuItem
                      className={
                        selectedOrganization.slug === org.slug
                          ? 'font-medium'
                          : ''
                      }
                      key={org.slug}
                      onClick={() => setSelectedOrganization(org)}
                    >
                      <div className="flex items-center gap-2">
                        <OrgIcon
                          className="h-4 w-4 flex-shrink-0 rounded object-cover"
                          org={org}
                        />
                        <div className="flex flex-col">
                          <span>{org.name}</span>
                          <span className="text-xs text-muted-foreground">
                            {org.slug}
                          </span>
                        </div>
                      </div>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            ))}

          {/* Quick Actions Dropdown */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                className="gap-2 border-tertiary bg-primary text-primary hover:bg-secondary"
                size="sm"
                variant="outline"
              >
                <Plus className="h-4 w-4" />
                <ChevronDown className="h-3 w-3" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuItem onClick={onNewDeployment}>
                <Rocket className="mr-2 h-4 w-4" />
                <span>New Deployment</span>
              </DropdownMenuItem>
              <DropdownMenuItem onClick={onNewOpsEntry}>
                <Activity className="mr-2 h-4 w-4" />
                <span>New Ops Log Entry</span>
              </DropdownMenuItem>
              <DropdownMenuItem onClick={onNewProject}>
                <FolderKanban className="mr-2 h-4 w-4" />
                <span>New Project</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          {/* User Profile Dropdown */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                className="rounded-full p-0 hover:bg-secondary"
                size="icon"
                variant="ghost"
              >
                {user?.email ? (
                  <Gravatar
                    alt={user?.display_name || user?.username || 'User'}
                    className="h-8 w-8 rounded-full"
                    email={user.email}
                    size={32}
                  />
                ) : (
                  <User className="h-4 w-4" />
                )}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              {user && (
                <div className="px-2 py-1.5 text-sm font-semibold">
                  {user.display_name || user.username}
                </div>
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => onViewChange?.('user-profile')}>
                <UserCircle className="mr-2 h-4 w-4" />
                <span>Profile</span>
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => navigate('/settings')}>
                <Settings className="mr-2 h-4 w-4" />
                <span>Settings</span>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={logout}>
                <LogOut className="mr-2 h-4 w-4" />
                <span>Sign Out</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          {/* Theme Toggle */}
          <Button
            className="rounded-full text-secondary hover:bg-secondary"
            onClick={toggleTheme}
            size="icon"
            variant="ghost"
          >
            {isDarkMode ? (
              <Sun className="h-4 w-4" />
            ) : (
              <Moon className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>
    </nav>
  )
}

function OrgIcon({ className, org }: { className: string; org: Organization }) {
  const Icon = useIcon(org.icon ?? null, Building2)
  return <Icon className={className} />
}
