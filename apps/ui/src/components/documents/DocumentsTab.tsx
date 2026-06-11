import type { ReactNode } from 'react'

import { ErrorBanner } from '@/components/ui/error-banner'
import type { Document, DocumentTemplate } from '@/types'

import { DocumentsPinboard } from './DocumentsPinboard'
import { DocumentsPinboardEmpty } from './DocumentsPinboardEmpty'
import { DocumentsPinboardNew } from './DocumentsPinboardNew'
import { DocumentsPinboardReader } from './DocumentsPinboardReader'
import { DocumentsTabSkeleton } from './DocumentsPinboardSkeleton'
import {
  type DocumentsScope,
  useDocumentsController,
} from './useDocumentsController'

export type { DocumentsScope } from './useDocumentsController'

export interface DocumentsListContext {
  displayNames?: Map<string, string>
  documents: Document[]
  onCreate: (template?: DocumentTemplate) => void
  onOpen: (documentId: string) => void
  onTogglePin: (document: Document) => void
}

interface Props {
  /** Rendered above the editor while creating (e.g. attachment picker). */
  creatingPrelude?: ReactNode
  initialAction?: string
  initialDocumentId?: string
  orgSlug: string
  /** Replace the default pinboard list view (e.g. the org-wide feed). */
  renderList?: (ctx: DocumentsListContext) => ReactNode
  scope: DocumentsScope
}

/**
 * The full documents experience for one {@link DocumentsScope}: the
 * pinboard list (or a custom list via `renderList`), the reader with
 * comments, and the editor — with view state mirrored into the URL.
 */
// fallow-ignore-next-line complexity
export function DocumentsTab({
  creatingPrelude,
  initialAction,
  initialDocumentId,
  orgSlug,
  renderList,
  scope,
}: Props) {
  const ctl = useDocumentsController(
    orgSlug,
    scope,
    initialDocumentId,
    initialAction,
  )

  if (ctl.isLoading) return <DocumentsTabSkeleton feed={!!renderList} />
  if (ctl.error)
    return <ErrorBanner error={ctl.error} title="Failed to load documents" />

  if (ctl.view.kind === 'creating') {
    return (
      <div className="space-y-3.5">
        {creatingPrelude}
        <DocumentsPinboardNew
          allDocuments={ctl.documents}
          onDiscard={ctl.handleDiscard}
          onSave={ctl.handleSave}
          orgSlug={orgSlug}
          saving={ctl.createPending}
          template={ctl.view.template}
        />
      </div>
    )
  }

  if (ctl.editingDocument) {
    return (
      <DocumentsPinboardNew
        allDocuments={ctl.documents}
        initialDocument={ctl.editingDocument}
        key={ctl.editingDocument.id}
        onDiscard={ctl.handleDiscard}
        onSave={ctl.handleSave}
        orgSlug={orgSlug}
        saving={ctl.updatePending}
      />
    )
  }

  if (ctl.selectedDocument) {
    const document = ctl.selectedDocument
    return (
      <DocumentsPinboardReader
        allDocuments={ctl.documents}
        comments={ctl.comments.comments}
        commentsBusy={ctl.comments.commentsBusy}
        currentUserEmail={ctl.currentUserEmail}
        deleting={ctl.deletePending}
        displayNames={ctl.displayNames}
        document={document}
        onAcknowledgeComment={ctl.comments.onAcknowledge}
        onBack={() => ctl.navigateToView({ kind: 'list' })}
        onCreateThread={ctl.comments.onCreateThread}
        onDelete={() => ctl.deleteDocument(document.id)}
        onDeleteComment={ctl.comments.onDelete}
        onEdit={() =>
          ctl.navigateToView({ documentId: document.id, kind: 'editing' })
        }
        onEditComment={ctl.comments.onEdit}
        onOpen={(id) => ctl.navigateToView({ documentId: id, kind: 'reading' })}
        onReplyComment={ctl.comments.onReply}
        onResolveThread={ctl.comments.onResolve}
        onTogglePin={() => ctl.togglePin(document)}
        orgSlug={orgSlug}
        projectId={scope.commentsProjectId}
      />
    )
  }

  const listContext: DocumentsListContext = {
    displayNames: ctl.displayNames,
    documents: ctl.documents,
    onCreate: ctl.handleCreate,
    onOpen: (id) => ctl.navigateToView({ documentId: id, kind: 'reading' }),
    onTogglePin: ctl.togglePin,
  }

  if (renderList) return <>{renderList(listContext)}</>

  if (ctl.documents.length === 0) {
    return (
      <DocumentsPinboardEmpty
        context={scopeTemplateContext(scope)}
        emptyHeading={scope.emptyHeading}
        onCreate={ctl.handleCreate}
        orgSlug={orgSlug}
        projectTypeSlugs={scope.projectTypeSlugs}
      />
    )
  }

  return (
    <DocumentsPinboard
      context={scopeTemplateContext(scope)}
      displayNames={ctl.displayNames}
      documents={ctl.documents}
      onCreate={ctl.handleCreate}
      onOpen={listContext.onOpen}
      onTogglePin={ctl.togglePin}
      orgSlug={orgSlug}
      projectTypeSlugs={scope.projectTypeSlugs}
      showAuthor={scope.showAuthor ?? true}
    />
  )
}

function scopeTemplateContext(
  scope: DocumentsScope,
): 'project' | 'project_type' | 'user' {
  return scope.templateContext === 'org' ? 'user' : scope.templateContext
}
