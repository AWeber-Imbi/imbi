import { useEffect, useMemo, useRef, useState } from 'react'

import {
  useIsMutating,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, XCircle } from 'lucide-react'
import Markdown from 'react-markdown'
import { toast } from 'sonner'

import {
  type AnalysisReport,
  type AnalysisResult,
  type AnalysisResultStatus,
  getProjectAnalysis,
  remediateAllAnalysisFindings,
  remediateAnalysisFinding,
  rescoreProject,
  runProjectAnalysis,
} from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Sk } from '@/components/ui/skeleton'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAuth } from '@/hooks/useAuth'
import { useCommitSync } from '@/hooks/useCommitSync'
import { useProjectDeploymentResync } from '@/hooks/useDeploymentResync'
import { useProjectPatch } from '@/hooks/useProjectPatch'
import { usePRSync } from '@/hooks/usePRSync'
import { extractApiErrorDetail } from '@/lib/apiError'
import { treatNotFoundAsNull } from '@/lib/queryHelpers'
import type { Project } from '@/types'

const STATUS_LABEL: Record<AnalysisResultStatus, string> = {
  fail: 'Fail',
  pass: 'Pass',
  warn: 'Warn',
}

const STATUS_BG: Record<AnalysisResultStatus, string> = {
  fail: 'bg-danger/10 border-danger/40',
  pass: 'bg-success/10 border-success/40',
  warn: 'bg-warning/10 border-warning/40',
}

const STATUS_TEXT: Record<AnalysisResultStatus, string> = {
  fail: 'text-danger',
  pass: 'text-success',
  warn: 'text-warning',
}

// fallow-ignore-next-line complexity
export function ProjectDoctorTab({ project }: { project: Project }) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const isAdmin = user?.is_admin === true
  const canAnalyze =
    isAdmin || (user?.permissions ?? []).includes('project:write')
  const canRescore =
    isAdmin || (user?.permissions ?? []).includes('scoring_policy:rescore')
  const canResyncDeployments =
    isAdmin || (user?.permissions ?? []).includes('project:deployment:write')

  const { scheduleScoreRefresh } = useProjectPatch(orgSlug, project.id)

  const reportQuery = useQuery({
    enabled: !!orgSlug && !!project.id,
    // A 404 means no report has been generated yet — treat it as a
    // normal empty state rather than a query error.
    queryFn: ({ signal }): Promise<AnalysisReport | null> =>
      treatNotFoundAsNull(() =>
        getProjectAnalysis(orgSlug, project.id, signal),
      ),
    queryKey: ['projectAnalysis', orgSlug, project.id],
    staleTime: 60 * 1000,
  })

  const analyzeMutation = useMutation({
    mutationFn: () => runProjectAnalysis(orgSlug, project.id),
    onError: (err) =>
      toast.error(`Analysis failed: ${extractApiErrorDetail(err)}`),
    onSuccess: (report) => {
      queryClient.setQueryData(['projectAnalysis', orgSlug, project.id], report)
      toast.success('Analysis complete')
    },
  })

  // Auto-analyze once when the tab opens and no report exists.
  const autoAnalyzed = useRef(false)
  const noReportYet =
    reportQuery.isSuccess && reportQuery.data === null && canAnalyze
  useEffect(() => {
    if (!autoAnalyzed.current && noReportYet) {
      autoAnalyzed.current = true
      analyzeMutation.mutate()
    }
  }, [analyzeMutation, noReportYet])

  const rescoreMutation = useMutation({
    mutationFn: () => rescoreProject(project.id),
    onError: (err) =>
      toast.error(`Recompute failed: ${extractApiErrorDetail(err)}`),
    onSuccess: () => {
      toast.success('Score recompute enqueued')
      scheduleScoreRefresh()
    },
  })

  // Invalidates the project + currentReleases + operationsLog query keys
  // once the background backfill completes so badges and deploy widgets
  // refresh.
  const resync = useProjectDeploymentResync(orgSlug, project.id, () => {
    for (const key of ['project', 'currentReleases', 'operationsLog']) {
      void queryClient.invalidateQueries({
        queryKey: [key, orgSlug, project.id],
      })
    }
  })

  // Shares the deployment:write gate: the backend requires a GitHub
  // deployment plugin (eligibility) plus a connected commit-sync plugin.
  const commitSync = useCommitSync(orgSlug, project.id, canResyncDeployments)

  // Same deployment:write gate: requires the GitHub deployment plugin
  // plus a connected github-pr-sync plugin for the service credential.
  const prSync = usePRSync(orgSlug, project.id, canResyncDeployments)

  const setReport = (report: AnalysisReport) =>
    queryClient.setQueryData(['projectAnalysis', orgSlug, project.id], report)

  // Shared key for every remediation mutation (fix-all and per-finding)
  // targeting this report. Both write a full report snapshot into the
  // same query cache, so we gate them behind a single in-flight guard to
  // stop concurrent responses from clobbering each other.
  const remediateKey = ['remediate', orgSlug, project.id]
  const isRemediating = useIsMutating({ mutationKey: remediateKey }) > 0

  const remediateAllMutation = useMutation({
    mutationFn: () => remediateAllAnalysisFindings(orgSlug, project.id),
    mutationKey: remediateKey,
    onError: (err) =>
      toast.error(`Fix all failed: ${extractApiErrorDetail(err)}`),
    onSuccess: (res) => {
      setReport(res.report)
      const fixed = res.outcomes.filter(
        (o) => o.result.status === 'fixed',
      ).length
      const failed = res.outcomes.filter(
        (o) => o.result.status === 'failed',
      ).length
      toast.success(
        failed > 0
          ? `Fixed ${fixed}, ${failed} could not be fixed`
          : `Fixed ${fixed} finding(s)`,
      )
    },
  })

  const report = reportQuery.data
  const results = report?.results ?? []
  const hasFixableFindings =
    report !== null &&
    report !== undefined &&
    results.some((r) => r.remediation != null)

  return (
    <div className="space-y-6">
      {(canAnalyze || canRescore || canResyncDeployments) && (
        <Card>
          <CardHeader>
            <CardTitle>Utility Functions</CardTitle>
          </CardHeader>
          <CardContent className="flex gap-2">
            {canAnalyze && (
              <Button
                disabled={analyzeMutation.isPending}
                onClick={() => analyzeMutation.mutate()}
                size="sm"
                variant="outline"
              >
                {analyzeMutation.isPending ? 'Analyzing...' : 'Analyze'}
              </Button>
            )}
            {canRescore && (
              <Button
                disabled={rescoreMutation.isPending}
                onClick={() => rescoreMutation.mutate()}
                size="sm"
                variant="outline"
              >
                {rescoreMutation.isPending ? 'Enqueuing...' : 'Recompute Score'}
              </Button>
            )}
            {canResyncDeployments && (
              <Button
                disabled={resync.isSyncing}
                onClick={() => resync.sync()}
                size="sm"
                variant="outline"
              >
                {resync.isSyncing ? 'Syncing...' : 'Sync Deployments'}
              </Button>
            )}
            {canResyncDeployments && (
              <Button
                disabled={commitSync.isSyncing}
                onClick={() => commitSync.sync()}
                size="sm"
                variant="outline"
              >
                {commitSync.isSyncing ? 'Syncing...' : 'Sync Commits & Tags'}
              </Button>
            )}
            {canResyncDeployments && (
              <Button
                disabled={prSync.isSyncing}
                onClick={() => prSync.sync()}
                size="sm"
                variant="outline"
              >
                {prSync.isSyncing ? 'Syncing...' : 'Sync PRs'}
              </Button>
            )}
            {canAnalyze && hasFixableFindings && (
              <Button
                disabled={isRemediating || analyzeMutation.isPending}
                onClick={() => remediateAllMutation.mutate()}
                size="sm"
                variant="outline"
              >
                {remediateAllMutation.isPending ? 'Fixing...' : 'Fix all'}
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Analysis Results</CardTitle>
        </CardHeader>
        <CardContent>
          {(reportQuery.isPending || analyzeMutation.isPending) && (
            <DoctorReportSkeleton />
          )}
          {reportQuery.isError && (
            <p className="text-sm text-red-600 dark:text-red-400">
              Failed to load analysis report.
            </p>
          )}
          {!reportQuery.isPending &&
            !reportQuery.isError &&
            report === null &&
            !analyzeMutation.isPending && (
              <p className="text-tertiary text-sm">
                No analysis has been run yet for this project.
              </p>
            )}
          {report && results.length === 0 && !analyzeMutation.isPending && (
            <p className="text-tertiary text-sm">
              No analysis plugins reported findings for this project.
            </p>
          )}
          {report && results.length > 0 && (
            <div className="space-y-4">
              {(['fail', 'warn', 'pass'] as const).map((status) => (
                <StatusSection
                  canFix={canAnalyze}
                  key={status}
                  onReport={setReport}
                  orgSlug={orgSlug}
                  projectId={project.id}
                  results={results}
                  status={status}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function DoctorReportSkeleton() {
  return (
    <div className="space-y-4">
      {[0, 1].map((s) => (
        <div className="space-y-2" key={s}>
          <Sk h={14} w={120} />
          {[0, 1].map((r) => (
            <div
              className="border-input flex items-center gap-3 rounded-md border px-3 py-2.5"
              key={r}
            >
              <Sk circle h={16} w={16} />
              <Sk className="flex-1" h={14} w="40%" />
              <Sk h={12} r={4} w={36} />
              <Sk h={12} r={4} w={72} />
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

function FixControls({
  onReport,
  orgSlug,
  projectId,
  result,
}: {
  onReport: (report: AnalysisReport) => void
  orgSlug: string
  projectId: string
  result: AnalysisResult
}) {
  const [confirmOpen, setConfirmOpen] = useState(false)
  const offer = result.remediation

  // Shares the report-wide remediation guard: any fix (this one, another
  // finding's, or fix-all) writing the same report cache blocks the rest.
  const remediateKey = ['remediate', orgSlug, projectId]
  const isRemediating = useIsMutating({ mutationKey: remediateKey }) > 0

  const fixMutation = useMutation({
    mutationFn: () =>
      remediateAnalysisFinding(orgSlug, projectId, {
        finding_slug: result.slug,
        plugin_id: result.plugin_id,
        remediation_id: offer?.id ?? '',
      }),
    mutationKey: remediateKey,
    onError: (err) => toast.error(`Fix failed: ${extractApiErrorDetail(err)}`),
    onSuccess: (res) => {
      onReport(res.report)
      if (res.result.status === 'failed') {
        toast.error(res.result.message)
      } else {
        toast.success(res.result.message)
      }
    },
  })

  if (offer == null) return null

  return (
    <div className="mt-2">
      <Button
        disabled={isRemediating}
        onClick={() =>
          offer.destructive ? setConfirmOpen(true) : fixMutation.mutate()
        }
        size="sm"
        variant="outline"
      >
        {fixMutation.isPending ? 'Fixing...' : offer.label}
      </Button>
      <ConfirmDialog
        confirmLabel={offer.label}
        description={offer.confirm ?? 'This action cannot be undone.'}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => {
          setConfirmOpen(false)
          fixMutation.mutate()
        }}
        open={confirmOpen}
        title={offer.label}
      />
    </div>
  )
}

function ResultPanel({
  canFix,
  onReport,
  orgSlug,
  projectId,
  result,
}: {
  canFix: boolean
  onReport: (report: AnalysisReport) => void
  orgSlug: string
  projectId: string
  result: AnalysisResult
}) {
  return (
    <Collapsible defaultOpen={result.status !== 'pass'}>
      <CollapsibleTrigger
        className={`flex w-full items-center gap-3 rounded-md border px-3 py-2 text-left text-sm ${STATUS_BG[result.status]}`}
      >
        <StatusIcon status={result.status} />
        <span className="flex-1 font-medium">{result.title}</span>
        <span className={`text-xs uppercase ${STATUS_TEXT[result.status]}`}>
          {STATUS_LABEL[result.status]}
        </span>
        <span className="text-tertiary font-mono text-xs">
          {result.plugin_slug}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent className="text-secondary max-w-none px-3 pt-2 pb-3 text-sm">
        <Markdown>{result.description}</Markdown>
        {canFix && (
          <FixControls
            onReport={onReport}
            orgSlug={orgSlug}
            projectId={projectId}
            result={result}
          />
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}

function StatusIcon({ status }: { status: AnalysisResultStatus }) {
  const className = `size-4 ${STATUS_TEXT[status]}`
  if (status === 'fail') return <XCircle className={className} />
  if (status === 'warn') return <AlertTriangle className={className} />
  return <CheckCircle2 className={className} />
}

function StatusSection({
  canFix,
  onReport,
  orgSlug,
  projectId,
  results,
  status,
}: {
  canFix: boolean
  onReport: (report: AnalysisReport) => void
  orgSlug: string
  projectId: string
  results: AnalysisResult[]
  status: AnalysisResultStatus
}) {
  const filtered = useMemo(
    () =>
      [...results]
        .filter((r) => r.status === status)
        .sort((a, b) => a.title.localeCompare(b.title)),
    [results, status],
  )
  if (filtered.length === 0) return null
  return (
    <div className="space-y-2">
      <h3 className="text-secondary text-sm font-medium uppercase">
        {STATUS_LABEL[status]} ({filtered.length})
      </h3>
      {filtered.map((r) => (
        <ResultPanel
          canFix={canFix}
          key={`${r.plugin_slug}:${r.slug}`}
          onReport={onReport}
          orgSlug={orgSlug}
          projectId={projectId}
          result={r}
        />
      ))}
    </div>
  )
}
