import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface SessionEntryProps {
  role: 'user' | 'assistant'
  content: string
}

export function SessionEntry({ role, content }: SessionEntryProps) {
  if (role === 'user') {
    return (
      <div className={`font-mono text-sm ${'text-info'}`}>
        <span className={`select-none ${'text-tertiary'}`}>{'> '}</span>
        {content}
      </div>
    )
  }

  return (
    <div
      className={`border-l-2 pl-4 text-sm ${'border-tertiary text-primary'}`}
    >
      <div className="prose prose-sm dark:prose-invert max-w-none [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
        <Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown>
      </div>
    </div>
  )
}

// Keep the old name as an alias for backwards compat during transition
export { SessionEntry as MessageBubble }
