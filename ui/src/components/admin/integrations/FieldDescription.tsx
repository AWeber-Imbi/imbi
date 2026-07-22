import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { cn } from '@/lib/utils'

interface FieldDescriptionProps {
  className?: string
  text: string
}

/**
 * Renders a plugin-authored field / option / capability description as inline
 * markdown. Plugin manifests write these in reStructuredText-flavored prose
 * where inline literals use double backticks (``api``). CommonMark treats a
 * double-backtick run as a valid code-span delimiter, so rendering through the
 * markdown pipeline collapses ``api`` to a single <code>api</code> instead of
 * showing the raw backticks. Paragraphs are unwrapped so the result stays
 * inline within the caller's small-text container.
 */
export function FieldDescription({ className, text }: FieldDescriptionProps) {
  return (
    <span
      className={cn(
        'text-xs text-tertiary [&_a]:underline [&_code]:rounded [&_code]:bg-secondary [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[0.92em]',
        className,
      )}
    >
      <Markdown
        components={{
          a: ({ node: _node, ...props }) => (
            <a {...props} rel="noopener noreferrer" target="_blank" />
          ),
          p: ({ children }) => <>{children}</>,
        }}
        remarkPlugins={[remarkGfm]}
      >
        {text}
      </Markdown>
    </span>
  )
}
