import { useMemo, useState } from 'react'

import { useParams } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'
import { Rss, Search, Table } from 'lucide-react'

import {
  createProjectTypeDocument,
  createUserDocument,
  deleteOrgDocument,
  listOrgDocuments,
  listProjectTypes,
  patchOrgDocument,
} from '@/api/endpoints'
import { CommandBar } from '@/components/CommandBar'
import { DocumentsFeed } from '@/components/documents/DocumentsFeed'
import {
  attachmentDisplay,
  documentTitle,
} from '@/components/documents/documentsHelpers'
import { DocumentsIndexTable } from '@/components/documents/DocumentsIndexTable'
import {
  type DocumentsListContext,
  DocumentsTab,
} from '@/components/documents/DocumentsTab'
import { NewDocumentMenu } from '@/components/documents/NewDocumentMenu'
import type { DocumentsScope } from '@/components/documents/useDocumentsController'
import { Navigation } from '@/components/Navigation'
import { Input } from '@/components/ui/input'
import { LoadingState } from '@/components/ui/loading-state'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAuth } from '@/hooks/useAuth'
import { usePageTitle } from '@/hooks/usePageTitle'
import { useUserDisplayNames } from '@/hooks/useUserDisplayNames'
import type { Document, DocumentTemplate, ProjectType } from '@/types'

/** Attachment choice for a document created from the org-wide page. */
type AttachTarget = 'user' | `pt:${string}`

/**
 * Top-level Documents page: every document in the organization,
 * whichever vertex it is attached to, as an activity feed and an
 * index table with the attachment as the first column.
 */
// fallow-ignore-next-line complexity
export function DocumentsIndexPage() {
  usePageTitle('Documents')
  const { subAction, subId } = useParams<{
    subAction?: string
    subId?: string
  }>()
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''
  const orgName = selectedOrganization?.name || orgSlug

  return (
    <div className="bg-tertiary text-primary min-h-screen">
      <Navigation currentView="documents" />
      <main
        className="px-6 pt-20 pb-12"
        style={{ paddingBottom: 'var(--assistant-height, 64px)' }}
      >
        <div className="mx-auto max-w-7xl">
          {!orgSlug && <LoadingState label="Loading organization…" />}
          {orgSlug && (
            <DocumentsIndexBody
              initialAction={subAction}
              initialDocumentId={subId}
              orgName={orgName}
              orgSlug={orgSlug}
            />
          )}
        </div>
      </main>
      <CommandBar />
    </div>
  )
}

function AttachToPicker({
  currentUserName,
  onChange,
  projectTypes,
  value,
}: {
  currentUserName: string
  onChange: (value: AttachTarget) => void
  projectTypes: ProjectType[]
  value: AttachTarget
}) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="text-secondary text-xs font-medium">Attach to</span>
      <Select onValueChange={(v) => onChange(v as AttachTarget)} value={value}>
        <SelectTrigger className="h-8 w-72">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="user">Personal — {currentUserName}</SelectItem>
          {projectTypes.map((pt) => (
            <SelectItem key={pt.slug} value={`pt:${pt.slug}`}>
              Project type — {pt.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

function DocumentsIndexBody({
  initialAction,
  initialDocumentId,
  orgName,
  orgSlug,
}: {
  initialAction?: string
  initialDocumentId?: string
  orgName: string
  orgSlug: string
}) {
  const [tab, setTab] = useState<'feed' | 'index'>('feed')
  const [search, setSearch] = useState('')
  const [attachTo, setAttachTo] = useState<AttachTarget>('user')

  const { data: projectTypes = [] } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listProjectTypes(orgSlug, signal),
    queryKey: ['projectTypes', orgSlug],
  })

  const { displayNames } = useUserDisplayNames()
  const { user } = useAuth()
  const currentUserEmail = user?.email ?? ''

  const scope = useMemo<DocumentsScope>(
    () => ({
      basePath: '/documents',
      commentsProjectId: null,
      create: (draft) =>
        attachTo === 'user'
          ? createUserDocument(orgSlug, currentUserEmail, draft)
          : createProjectTypeDocument(orgSlug, attachTo.slice(3), draft),
      list: (signal) => listOrgDocuments(orgSlug, { limit: 500 }, signal),
      patch: (documentId, operations) =>
        patchOrgDocument(orgSlug, documentId, operations),
      queryKey: ['orgDocuments', orgSlug] as const,
      remove: (documentId) => deleteOrgDocument(orgSlug, documentId),
      templateContext: 'org',
    }),
    [orgSlug, attachTo, currentUserEmail],
  )

  // Pre-select the attachment from the template's type where it is
  // unambiguous; 'global' and blank documents default to personal.
  const presetAttachment = (template?: DocumentTemplate) => {
    if (template?.type === 'project_type' && template.project_type_slugs[0]) {
      setAttachTo(`pt:${template.project_type_slugs[0]}`)
    } else {
      setAttachTo('user')
    }
  }

  const renderList = (ctx: DocumentsListContext) => (
    <DocumentsIndexList
      ctx={ctx}
      onCreate={(template) => {
        presetAttachment(template)
        ctx.onCreate(template)
      }}
      orgName={orgName}
      orgSlug={orgSlug}
      search={search}
      setSearch={setSearch}
      setTab={setTab}
      tab={tab}
    />
  )

  return (
    <DocumentsTab
      creatingPrelude={
        <AttachToPicker
          currentUserName={displayNames?.get(currentUserEmail) ?? 'you'}
          onChange={setAttachTo}
          projectTypes={projectTypes}
          value={attachTo}
        />
      }
      initialAction={initialAction}
      initialDocumentId={initialDocumentId}
      orgSlug={orgSlug}
      renderList={renderList}
      scope={scope}
    />
  )
}

function DocumentsIndexList({
  ctx,
  onCreate,
  orgName,
  orgSlug,
  search,
  setSearch,
  setTab,
  tab,
}: {
  ctx: DocumentsListContext
  onCreate: (template?: DocumentTemplate) => void
  orgName: string
  orgSlug: string
  search: string
  setSearch: (value: string) => void
  setTab: (value: 'feed' | 'index') => void
  tab: 'feed' | 'index'
}) {
  const searched = useMemo(
    () => filterDocuments(sortByUpdated(ctx.documents), search),
    [ctx.documents, search],
  )

  return (
    <>
      {/* Header */}
      <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-primary m-0 text-2xl font-semibold tracking-[-0.02em]">
            Documents
          </h1>
          <div className="text-tertiary mt-1 text-sm">
            All documents across the {orgName} organization ·{' '}
            {ctx.documents.length}{' '}
            {ctx.documents.length === 1 ? 'document' : 'documents'}
          </div>
        </div>
        <div className="flex items-center gap-2.5">
          <div className="relative w-70">
            <Search className="text-tertiary absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2" />
            <Input
              className="h-8 pl-8"
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search all documents…"
              value={search}
            />
          </div>
          <NewDocumentMenu
            context="org"
            onCreate={onCreate}
            orgSlug={orgSlug}
          />
        </div>
      </div>

      {/* Feed | Index tabs */}
      <Tabs onValueChange={(v) => setTab(v as 'feed' | 'index')} value={tab}>
        <TabsList className="mb-5">
          <TabsTrigger className="gap-1.5" value="feed">
            <Rss className="size-3.5" />
            Activity feed
          </TabsTrigger>
          <TabsTrigger className="gap-1.5" value="index">
            <Table className="size-3.5" />
            Index ({searched.length})
          </TabsTrigger>
        </TabsList>
      </Tabs>

      {tab === 'feed' && (
        <DocumentsFeed
          displayNames={ctx.displayNames}
          documents={searched}
          onOpen={ctx.onOpen}
        />
      )}
      {tab === 'index' && (
        <DocumentsIndexTable
          displayNames={ctx.displayNames}
          documents={searched}
          onOpen={ctx.onOpen}
          onTogglePin={ctx.onTogglePin}
        />
      )}
    </>
  )
}

function filterDocuments(documents: Document[], search: string): Document[] {
  const q = search.trim().toLowerCase()
  if (!q) return documents
  return documents.filter((n) => {
    const attached = attachmentDisplay(n)
    return [
      documentTitle(n),
      n.content,
      attached.name,
      attached.sub,
      n.attached_to?.team ?? '',
      n.created_by,
      n.created_by_name ?? '',
      n.tags.map((t) => t.name).join(' '),
    ]
      .join(' ')
      .toLowerCase()
      .includes(q)
  })
}

function sortByUpdated(documents: Document[]): Document[] {
  return [...documents].sort((a, b) =>
    (b.updated_at ?? b.created_at).localeCompare(a.updated_at ?? a.created_at),
  )
}
