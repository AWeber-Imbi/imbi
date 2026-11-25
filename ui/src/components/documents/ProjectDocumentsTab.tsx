import { useMemo } from 'react'

import {
  createProjectDocument,
  deleteProjectDocument,
  listProjectDocuments,
  patchProjectDocument,
} from '@/api/endpoints'

import { type DocumentsScope, DocumentsTab } from './DocumentsTab'

interface Props {
  basePath: string
  initialAction?: string
  initialDocumentId?: string
  orgSlug: string
  projectId: string
  projectTypeSlugs?: string[]
}

/** The project-detail Documents tab — a project-scoped {@link DocumentsTab}. */
export function ProjectDocumentsTab({
  basePath,
  initialAction,
  initialDocumentId,
  orgSlug,
  projectId,
  projectTypeSlugs,
}: Props) {
  const scope = useMemo<DocumentsScope>(
    () => ({
      basePath,
      commentsProjectId: projectId,
      create: (draft) => createProjectDocument(orgSlug, projectId, draft),
      list: (signal) =>
        listProjectDocuments(orgSlug, projectId, undefined, signal),
      patch: (documentId, operations) =>
        patchProjectDocument(orgSlug, projectId, documentId, operations),
      projectTypeSlugs,
      queryKey: ['projectDocuments', orgSlug, projectId] as const,
      remove: (documentId) =>
        deleteProjectDocument(orgSlug, projectId, documentId),
      templateContext: 'project',
    }),
    [basePath, orgSlug, projectId, projectTypeSlugs],
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
