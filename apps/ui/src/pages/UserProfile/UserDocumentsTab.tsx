import { useMemo } from 'react'

import {
  createUserDocument,
  deleteOrgDocument,
  listUserDocuments,
  patchOrgDocument,
} from '@/api/endpoints'
import {
  type DocumentsScope,
  DocumentsTab,
} from '@/components/documents/DocumentsTab'

interface Props {
  email: string
  initialAction?: string
  initialDocumentId?: string
  orgSlug: string
}

/**
 * The profile Documents tab — the exact project documents experience,
 * scoped to documents attached to this user. The Author column is
 * omitted (every document here is the profiled user's) and new
 * documents attach to the user, offering user + global templates.
 */
export function UserDocumentsTab({
  email,
  initialAction,
  initialDocumentId,
  orgSlug,
}: Props) {
  const scope = useMemo<DocumentsScope>(
    () => ({
      basePath: `/users/${encodeURIComponent(email)}/documents`,
      commentsProjectId: null,
      create: (draft) => createUserDocument(orgSlug, email, draft),
      emptyHeading: 'No documents yet for this user',
      list: (signal) => listUserDocuments(orgSlug, email, signal),
      patch: (documentId, operations) =>
        patchOrgDocument(orgSlug, documentId, operations),
      queryKey: ['userDocuments', orgSlug, email] as const,
      remove: (documentId) => deleteOrgDocument(orgSlug, documentId),
      showAuthor: false,
      templateContext: 'user',
    }),
    [orgSlug, email],
  )

  return (
    <DocumentsTab
      initialAction={initialAction}
      initialDocumentId={initialDocumentId}
      orgSlug={orgSlug}
      scope={scope}
    />
  )
}
