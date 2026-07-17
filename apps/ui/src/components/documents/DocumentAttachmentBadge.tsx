import { Link } from 'react-router-dom'

import { FolderKanban, Layers, User } from 'lucide-react'

import type { DocumentAttachment } from '@/types'

const KIND_META: Record<
  DocumentAttachment['kind'],
  { icon: typeof User; label: string }
> = {
  project: { icon: FolderKanban, label: 'Project' },
  project_type: { icon: Layers, label: 'Project type' },
  user: { icon: User, label: 'Personal' },
}

/**
 * The attachment eyebrow shown above a document's title in the org-wide
 * reader, where the container no longer implies what the document is
 * bound to. Encodes the attachment kind (project, project type, or
 * personal) with a matching icon and label; the project name links to
 * the project.
 */
export function DocumentAttachmentBadge({
  attachment,
}: {
  attachment: DocumentAttachment
}) {
  const { icon: Icon, label } = KIND_META[attachment.kind]
  const name = attachment.name || attachment.id

  return (
    <div className="mb-2.5 flex items-center gap-1.5 text-[12.5px] leading-none">
      <Icon className="text-tertiary size-3.5 shrink-0" />
      <span className="text-overline text-tertiary uppercase">{label}</span>
      <span className="text-tertiary">·</span>
      {attachment.kind === 'project' ? (
        <Link
          className="text-secondary hover:text-action truncate font-medium no-underline"
          to={`/projects/${attachment.id}`}
        >
          {name}
        </Link>
      ) : (
        <span className="text-secondary truncate font-medium">{name}</span>
      )}
    </div>
  )
}
