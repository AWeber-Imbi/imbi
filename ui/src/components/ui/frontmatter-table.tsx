import Markdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { formatFrontmatterValue } from '@/lib/frontmatter'

interface FrontmatterTableProps {
  meta: Record<string, unknown>
}

// A cell holds one value, so drop the paragraph wrapper around it.
const CELL_COMPONENTS: Components = {
  a: ({ node: _node, ...props }) => (
    <a {...props} rel="noopener noreferrer" target="_blank" />
  ),
  p: ({ children }) => <>{children}</>,
}

/** Render parsed YAML frontmatter as a key/value table of markdown. */
export function FrontmatterTable({ meta }: FrontmatterTableProps) {
  return (
    <div className="frontmatter">
      <table>
        <tbody>
          {Object.entries(meta).map(([key, value]) => (
            <tr key={key}>
              <th scope="row">{key}</th>
              <td>
                <Markdown
                  components={CELL_COMPONENTS}
                  remarkPlugins={[remarkGfm]}
                >
                  {formatFrontmatterValue(value)}
                </Markdown>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
