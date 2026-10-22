import { useMemo } from 'react'

import Markdown, { type Components, type Options } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { FrontmatterTable } from '@/components/ui/frontmatter-table'
import { useProjectRepoUrl } from '@/contexts/ProjectRepoContext'
import { splitFrontmatter } from '@/lib/frontmatter'
import { remarkGithubRefs } from '@/lib/github-refs'

interface RichMarkdownProps {
  children: string
}

const COMPONENTS: Components = {
  a: ({ node: _node, ...props }) => (
    <a {...props} rel="noopener noreferrer" target="_blank" />
  ),
}

/**
 * GFM markdown with links opening in a new tab and, under a project page
 * whose GitHub repository is known, ``#N`` references linked to their
 * issue/PR. A leading YAML frontmatter block renders as a table. Callers
 * own the surrounding ``document-markdown`` wrapper.
 */
export function RichMarkdown({ children }: RichMarkdownProps) {
  const repoUrl = useProjectRepoUrl()
  const remarkPlugins = useMemo<Options['remarkPlugins']>(
    () =>
      repoUrl ? [remarkGfm, [remarkGithubRefs, { repoUrl }]] : [remarkGfm],
    [repoUrl],
  )
  const { body, meta } = splitFrontmatter(children)
  return (
    <>
      {meta && <FrontmatterTable meta={meta} />}
      <Markdown components={COMPONENTS} remarkPlugins={remarkPlugins}>
        {body}
      </Markdown>
    </>
  )
}
