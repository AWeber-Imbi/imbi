import { Layers } from 'lucide-react'

interface ProjectTypeManagementProps {
  isDarkMode: boolean
}

export function ProjectTypeManagement({ isDarkMode }: ProjectTypeManagementProps) {
  return (
    <div className="flex flex-col items-center justify-center py-24">
      <Layers className={`w-16 h-16 mb-4 ${isDarkMode ? 'text-gray-600' : 'text-gray-300'}`} />
      <h3 className={`text-xl font-semibold mb-2 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
        Coming Soon
      </h3>
      <p className={`text-center max-w-md ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
        Project type management will allow you to define and configure the types of projects tracked in your service catalog.
      </p>
    </div>
  )
}
