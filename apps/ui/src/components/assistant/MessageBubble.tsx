import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface SessionEntryProps {
  content: string
  role: 'assistant' | 'user'
}

export function SessionEntry({ content, role }: SessionEntryProps) {
  if (role === 'user') {
    return (
      <div className="font-mono text-sm text-info">
        <span className="select-none text-tertiary">{'> '}</span>
        {content}
      </div>
    )
  }

  return (
    <div className="border-l-2 border-tertiary pl-4 text-sm text-primary">
      <div className="prose prose-sm dark:prose-invert max-w-none [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
        <Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown>
      </div>
    </div>
  )
}
