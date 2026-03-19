interface StatWidgetProps {
  title: string
  value: string
  icon: string
  isDarkMode: boolean
}

export function StatWidget({
  title,
  value,
  icon,
  isDarkMode,
}: StatWidgetProps) {
  return (
    <div
      className={`rounded-lg p-6 ${
        isDarkMode
          ? 'border border-gray-700 bg-gray-800'
          : 'border border-gray-200 bg-white'
      }`}
    >
      <div className="flex items-center justify-between">
        <div>
          <p
            className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
          >
            {title}
          </p>
          <p
            className={`mt-2 text-3xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
          >
            {value}
          </p>
        </div>
        <div className="text-4xl">{icon}</div>
      </div>
    </div>
  )
}
