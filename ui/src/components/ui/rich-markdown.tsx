import { useMemo } from 'react'

import Markdown, { type Components, type Options } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { FrontmatterTable } from '@/components/ui/frontmatter-table'
import { useProjectRepoUrl } from '@/contexts/ProjectRepoContext'
import { splitFrontmatter } from '@/lib/frontmatter'
import { remarkGithubRefs } from '@/lib/github-refs'

interface RichMarkdownProps {
  children: string
  /**
   * Render images as links instead of loading them. Use it for text an
   * agent or another untrusted author wrote: an image loads with no
   * click, so its URL can carry data out of the page.
   */
  imagesAsLinks?: boolean
}

const COMPONENTS: Components = {
  a: ({ node: _node, ...props }) => (
    <a {...props} rel="noopener noreferrer" target="_blank" />
  ),
}

const IMAGES_AS_LINKS: Components = {
  ...COMPONENTS,
  img: ({ alt, src }) => (
    <a href={src} rel="noopener noreferrer" target="_blank">
      {alt || src}
    </a>
  ),
}

/**
 * GFM markdown with links opening in a new tab and, under a project page
 * whose GitHub repository is known, ``#N`` references linked to their
 * issue/PR. A leading YAML frontmatter block renders as a table. Callers
 * own the surrounding ``document-markdown`` wrapper.
 */
export function RichMarkdown({
  children,
  imagesAsLinks = false,
}: RichMarkdownProps) {
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
      <Markdown
        components={imagesAsLinks ? IMAGES_AS_LINKS : COMPONENTS}
        remarkPlugins={remarkPlugins}
      >
        {body}
      </Markdown>
    </>
  )
}
