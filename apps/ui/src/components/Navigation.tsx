import { useNavigate, useLocation } from 'react-router-dom'
import {
  Settings,
  User,
  Rocket,
  FolderKanban,
  Activity,
  BarChart3,
  Plus,
  ChevronDown,
  UserCircle,
  LogOut,
  Moon,
  Sun,
  Building2,
} from 'lucide-react'
import { Button } from './ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from './ui/dropdown-menu'
import { Gravatar } from './ui/gravatar'
import { useAuth } from '@/hooks/useAuth'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useTheme } from '@/contexts/ThemeContext'
import { UserResponse } from '@/types'
import logoLight from '@/assets/logo-light.svg'
import logoDark from '@/assets/logo-dark.svg'
import { useMemo } from 'react'

interface NavigationProps {
  currentView?: string
  onViewChange?: (view: string) => void
  onNewOpsEntry?: () => void
  onNewProject?: () => void
  onNewDeployment?: () => void
}

export function Navigation({
  currentView,
  onViewChange,
  onNewOpsEntry,
  onNewDeployment,
  onNewProject,
}: NavigationProps) {
  const { isDarkMode, toggleTheme } = useTheme()
  const { user, logout } = useAuth()
  const { organizations, selectedOrganization, setSelectedOrganization } =
    useOrganization()
  const navigate = useNavigate()
  const location = useLocation()

  // Check if user is admin (safely cast to UserResponse to access is_admin)
  const isAdmin = (user as UserResponse | null)?.is_admin === true

  // Memoize navItems to avoid array mutation on every render
  const navItems = useMemo(() => {
    const items = [
      {
        id: 'projects',
        label: 'Projects',
        icon: FolderKanban,
        path: '/projects',
      },
      {
        id: 'deployments',
        label: 'Deployments',
        icon: Rocket,
        path: '/deployments',
      },
      {
        id: 'operations',
        label: 'Operations Log',
        icon: Activity,
        path: '/operations',
      },
      { id: 'reports', label: 'Reports', icon: BarChart3, path: '/reports' },
    ]

    // Add Admin nav item if user is admin
    if (isAdmin) {
      items.push({
        id: 'admin',
        label: 'Admin',
        icon: Settings,
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
          <button
            onClick={() => navigate('/dashboard')}
            className="flex items-center gap-2 rounded-lg px-2 py-1.5 transition-all hover:bg-secondary"
          >
            <img
              src={isDarkMode ? logoDark : logoLight}
              alt="Imbi"
              className="h-8 w-8"
            />
            <span className="text-primary" style={{ fontWeight: 800 }}>
              Imbi
            </span>
          </button>

          {/* Navigation Items */}
          <div className="hidden items-center gap-1 md:flex">
            {navItems.map((item) => {
              const Icon = item.icon
              const isActive = activeView === item.id
              return (
                <button
                  key={item.id}
                  onClick={() => navigate(item.path)}
                  className={`flex items-center gap-2 rounded-lg px-4 py-2 transition-colors ${
                    isActive
                      ? 'bg-amber-bg text-amber-text'
                      : 'text-secondary hover:bg-secondary hover:text-primary'
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  <span>{item.label}</span>
                </button>
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
                variant="outline"
                size="sm"
                className="pointer-events-none max-w-[200px] cursor-default gap-2 border-tertiary bg-primary text-primary"
              >
                {selectedOrganization.icon ? (
                  <img
                    src={selectedOrganization.icon}
                    alt=""
                    className="h-4 w-4 flex-shrink-0 rounded object-cover"
                  />
                ) : (
                  <Building2 className="h-4 w-4 flex-shrink-0" />
                )}
                <span className="truncate">{selectedOrganization.name}</span>
              </Button>
            ) : (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    className="max-w-[200px] gap-2 border-tertiary bg-primary text-primary hover:bg-secondary"
                  >
                    {selectedOrganization.icon ? (
                      <img
                        src={selectedOrganization.icon}
                        alt=""
                        className="h-4 w-4 flex-shrink-0 rounded object-cover"
                      />
                    ) : (
                      <Building2 className="h-4 w-4 flex-shrink-0" />
                    )}
                    <span className="truncate">
                      {selectedOrganization.name}
                    </span>
                    <ChevronDown className="h-3 w-3 flex-shrink-0" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-56">
                  {organizations.map((org) => (
                    <DropdownMenuItem
                      key={org.slug}
                      onClick={() => setSelectedOrganization(org)}
                      className={
                        selectedOrganization.slug === org.slug
                          ? 'font-medium'
                          : ''
                      }
                    >
                      <div className="flex items-center gap-2">
                        {org.icon ? (
                          <img
                            src={org.icon}
                            alt=""
                            className="h-4 w-4 flex-shrink-0 rounded object-cover"
                          />
                        ) : (
                          <Building2 className="h-4 w-4 flex-shrink-0 text-muted-foreground" />
                        )}
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
                variant="outline"
                size="sm"
                className="gap-2 border-tertiary bg-primary text-primary hover:bg-secondary"
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
                variant="ghost"
                size="icon"
                className="rounded-full p-0 hover:bg-secondary"
              >
                {user?.email ? (
                  <Gravatar
                    email={user.email}
                    size={32}
                    alt={user?.display_name || user?.username || 'User'}
                    className="h-8 w-8 rounded-full"
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
            variant="ghost"
            size="icon"
            className="rounded-full text-secondary hover:bg-secondary"
            onClick={toggleTheme}
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
