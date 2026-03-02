import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface SessionEntryProps {
  role: 'user' | 'assistant'
  content: string
  isDarkMode: boolean
}

export function SessionEntry({
  role,
  content,
  isDarkMode,
}: SessionEntryProps) {
  if (role === 'user') {
    return (
      <div
        className={`font-mono text-sm ${
          isDarkMode ? 'text-blue-400' : 'text-[#2A4DD0]'
        }`}
      >
        <span
          className={`select-none ${
            isDarkMode ? 'text-gray-500' : 'text-gray-400'
          }`}
        >
          {'> '}
        </span>
        {content}
      </div>
    )
  }

  return (
    <div
      className={`text-sm pl-4 border-l-2 ${
        isDarkMode
          ? 'border-gray-700 text-gray-300'
          : 'border-gray-200 text-gray-800'
      }`}
    >
      <div className="prose prose-sm max-w-none dark:prose-invert [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
        <Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown>
      </div>
    </div>
  )
}

// Keep the old name as an alias for backwards compat during transition
export { SessionEntry as MessageBubble }
