import { Globe } from 'lucide-react'

interface EnvironmentManagementProps {
  isDarkMode: boolean
}

export function EnvironmentManagement({ isDarkMode }: EnvironmentManagementProps) {
  return (
    <div className="flex flex-col items-center justify-center py-24">
      <Globe className={`w-16 h-16 mb-4 ${isDarkMode ? 'text-gray-600' : 'text-gray-300'}`} />
      <h3 className={`text-xl font-semibold mb-2 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
        Coming Soon
      </h3>
      <p className={`text-center max-w-md ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
        Environment management will allow you to define and configure deployment targets for your projects.
      </p>
    </div>
  )
}
