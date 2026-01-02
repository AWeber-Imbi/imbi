import { useState } from 'react'
import { Users, ChevronRight } from 'lucide-react'
import { UserManagement } from './admin/UserManagement'
import { useNavigate } from 'react-router-dom'

interface AdminProps {
  isDarkMode: boolean
}

type AdminSection = 'users'

export function Admin({ isDarkMode }: AdminProps) {
  const navigate = useNavigate()
  const [currentSection, setCurrentSection] = useState<AdminSection>('users')

  const adminSections = [
    { id: 'users' as AdminSection, label: 'User Management', icon: Users, description: 'Manage user accounts and service accounts' },
  ]

  const currentSectionData = adminSections.find(s => s.id === currentSection)

  return (
    <div className={`min-h-screen ${isDarkMode ? 'bg-gray-900' : 'bg-slate-50'}`}>
      <div className="flex">
        {/* Side Navigation */}
        <aside className={`w-72 min-h-screen border-r flex flex-col ${
          isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
        }`}>
          <div className={`p-6 border-b ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}>
            <h2 className={`text-xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>Administration</h2>
            <p className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
              System configuration and management
            </p>
          </div>

          <nav className="p-4 space-y-1 flex-1">
            {adminSections.map((section) => {
              const Icon = section.icon
              const isActive = currentSection === section.id
              return (
                <button
                  key={section.id}
                  onClick={() => setCurrentSection(section.id)}
                  className={`w-full flex items-start gap-3 px-4 py-3 rounded-lg transition-colors text-left ${
                    isActive
                      ? isDarkMode
                        ? 'bg-blue-900 text-blue-300'
                        : 'bg-blue-50 text-[#2A4DD0]'
                      : isDarkMode
                        ? 'text-gray-300 hover:bg-gray-700 hover:text-white'
                        : 'text-gray-700 hover:bg-gray-100 hover:text-gray-900'
                  }`}
                >
                  <Icon className="w-5 h-5 mt-0.5 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className={`font-medium ${isActive ? (isDarkMode ? 'text-blue-300' : 'text-[#2A4DD0]') : ''}`}>
                      {section.label}
                    </div>
                    <div className={`text-xs mt-0.5 ${
                      isActive
                        ? isDarkMode ? 'text-blue-400/70' : 'text-[#2A4DD0]/70'
                        : isDarkMode ? 'text-gray-500' : 'text-gray-500'
                    }`}>
                      {section.description}
                    </div>
                  </div>
                  {isActive && <ChevronRight className="w-4 h-4 mt-1 flex-shrink-0" />}
                </button>
              )
            })}
          </nav>

          <div className={`p-4 border-t ${
            isDarkMode ? 'border-gray-700' : 'border-gray-200'
          }`}>
            <button
              onClick={() => navigate('/dashboard')}
              className={`w-full px-4 py-2 text-sm rounded-lg transition-colors ${
                isDarkMode
                  ? 'text-gray-400 hover:bg-gray-700 hover:text-white'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
              }`}
            >
              ← Back to Dashboard
            </button>
          </div>
        </aside>

        {/* Main Content */}
        <main className="flex-1">
          {/* Section Header */}
          <div className={`border-b ${isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'}`}>
            <div className="px-8 py-6">
              <div className="flex items-center gap-3">
                {currentSectionData && <currentSectionData.icon className={`w-6 h-6 ${isDarkMode ? 'text-blue-400' : 'text-[#2A4DD0]'}`} />}
                <div>
                  <h1 className={`text-2xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>{currentSectionData?.label}</h1>
                  <p className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                    {currentSectionData?.description}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Section Content */}
          <div className="p-8">
            {currentSection === 'users' && <UserManagement isDarkMode={isDarkMode} />}
          </div>
        </main>
      </div>
    </div>
  )
}
