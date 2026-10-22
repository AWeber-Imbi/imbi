import { formatFrontmatterValue } from '@/lib/frontmatter'

interface FrontmatterTableProps {
  meta: Record<string, unknown>
}

/** Render parsed YAML frontmatter as a key/value table. */
export function FrontmatterTable({ meta }: FrontmatterTableProps) {
  return (
    <div className="frontmatter">
      <table>
        <tbody>
          {Object.entries(meta).map(([key, value]) => (
            <tr key={key}>
              <th scope="row">{key}</th>
              <td>{formatFrontmatterValue(value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
