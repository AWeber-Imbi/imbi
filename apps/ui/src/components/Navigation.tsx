import { useNavigate, useLocation } from 'react-router-dom'
import { Search, Settings, User, Rocket, FolderKanban, Activity, BarChart3, Sparkles, Plus, ChevronDown, UserCircle, LogOut, Moon, Sun } from 'lucide-react'
import { Button } from './ui/button'
import { Input } from './ui/input'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from './ui/dropdown-menu'
import { useAuth } from '@/hooks/useAuth'
import imbiLogo from '@/assets/logo.svg'

interface NavigationProps {
  currentView?: string
  onViewChange?: (view: string) => void
  onChatToggle?: () => void
  onNewOpsEntry?: () => void
  onNewProject?: () => void
  onNewDeployment?: () => void
  isDarkMode: boolean
  onThemeToggle: () => void
}

export function Navigation({
  currentView,
  onViewChange,
  onChatToggle,
  onNewOpsEntry,
  onNewDeployment,
  onNewProject,
  isDarkMode,
  onThemeToggle
}: NavigationProps) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const navItems = [
    { id: 'deployments', label: 'Deployments', icon: Rocket, path: '/deployments' },
    { id: 'projects', label: 'Projects', icon: FolderKanban, path: '/projects' },
    { id: 'operations', label: 'Operations Log', icon: Activity, path: '/operations' },
    { id: 'reports', label: 'Reports', icon: BarChart3, path: '/reports' },
  ]

  // Determine active view from route if not explicitly provided
  const activeView = currentView || navItems.find(item => location.pathname === item.path)?.id || 'dashboard'

  return (
    <nav className={`fixed top-0 left-0 right-0 z-50 border-b transition-colors ${
      isDarkMode
        ? 'bg-gray-800 border-gray-700'
        : 'bg-white border-gray-200'
    }`}>
      <div className="flex items-center justify-between px-6 h-16">
        {/* Logo and Brand */}
        <div className="flex items-center gap-8">
          <button
            onClick={() => navigate('/dashboard')}
            className={`flex items-center gap-2 px-2 py-1.5 rounded-lg transition-all ${
              isDarkMode
                ? 'hover:bg-gray-700'
                : 'hover:bg-gray-100'
            }`}
          >
            <img src={imbiLogo} alt="Imbi" className="w-8 h-8" />
            <span className={isDarkMode ? 'text-white' : 'text-gray-900'}>
              Imbi
            </span>
          </button>

          {/* Navigation Items */}
          <div className="hidden md:flex items-center gap-1">
            {navItems.map((item) => {
              const Icon = item.icon
              const isActive = activeView === item.id
              return (
                <button
                  key={item.id}
                  onClick={() => navigate(item.path)}
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
                    isActive
                      ? isDarkMode
                        ? 'bg-blue-900 text-blue-300'
                        : 'bg-blue-50 text-[#2A4DD0]'
                      : isDarkMode
                        ? 'text-gray-300 hover:bg-gray-700 hover:text-white'
                        : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  <span>{item.label}</span>
                </button>
              )
            })}
          </div>
        </div>

        {/* Right Side Actions */}
        <div className="flex items-center gap-3">
          {/* Search */}
          <div className="hidden sm:block relative">
            <Search className={`absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 ${
              isDarkMode ? 'text-gray-400' : 'text-gray-400'
            }`} />
            <Input
              type="text"
              placeholder="Search projects..."
              className={`pl-9 w-64 h-9 ${
                isDarkMode
                  ? 'bg-gray-700 border-gray-600 text-white placeholder:text-gray-400'
                  : 'bg-white border-gray-300 text-gray-900 placeholder:text-gray-500'
              }`}
            />
          </div>

          <Button
            variant="default"
            size="sm"
            onClick={onChatToggle}
            className="bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-700 hover:to-blue-700"
          >
            <Sparkles className="w-4 h-4 mr-2" />
            <span className="hidden sm:inline">AI Assistant</span>
          </Button>

          {/* Quick Actions Dropdown */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                className={`gap-2 ${
                  isDarkMode
                    ? 'border-blue-500 text-blue-400 hover:bg-gray-700 bg-gray-800'
                    : 'border-gray-300 text-gray-700 hover:bg-gray-50 bg-white'
                }`}
              >
                <Plus className="w-4 h-4" />
                <ChevronDown className="w-3 h-3" />
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
                className={`rounded-full ${isDarkMode ? 'text-white hover:bg-gray-700' : 'text-gray-700 hover:bg-gray-100'}`}
              >
                <User className="w-4 h-4" />
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
              <DropdownMenuItem onClick={() => onViewChange?.('settings')}>
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
            className={`rounded-full ${isDarkMode ? 'text-white hover:bg-gray-700' : 'text-gray-700 hover:bg-gray-100'}`}
            onClick={onThemeToggle}
          >
            {isDarkMode ? (
              <Sun className="w-4 h-4" />
            ) : (
              <Moon className="w-4 h-4" />
            )}
          </Button>
        </div>
      </div>
    </nav>
  )
}
