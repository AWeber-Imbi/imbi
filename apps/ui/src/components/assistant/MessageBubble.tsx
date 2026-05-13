import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface SessionEntryProps {
  content: string
  role: 'assistant' | 'user'
}

export function SessionEntry({ content, role }: SessionEntryProps) {
  if (role === 'user') {
    return (
      <div className="text-info font-mono text-sm">
        <span className="text-tertiary select-none">{'> '}</span>
        {content}
      </div>
    )
  }

  return (
    <div className="border-tertiary text-primary border-l-2 pl-4 text-sm">
      <div className="document-markdown max-w-none [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
        <Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown>
      </div>
    </div>
  )
}
