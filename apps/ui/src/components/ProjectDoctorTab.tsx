import { useEffect, useMemo, useRef } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, XCircle } from 'lucide-react'
import Markdown from 'react-markdown'
import { toast } from 'sonner'

import {
  type AnalysisReport,
  type AnalysisResult,
  type AnalysisResultStatus,
  getProjectAnalysis,
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
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAuth } from '@/hooks/useAuth'
import { useCommitSync } from '@/hooks/useCommitSync'
import { useProjectDeploymentResync } from '@/hooks/useDeploymentResync'
import { useProjectPatch } from '@/hooks/useProjectPatch'
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

  const resyncMutation = useProjectDeploymentResync(orgSlug, project.id)

  // Shares the deployment:write gate: the backend requires a GitHub
  // deployment plugin (eligibility) plus a connected commit-sync plugin.
  const commitSync = useCommitSync(orgSlug, project.id, canResyncDeployments)

  const report = reportQuery.data
  const results = report?.results ?? []

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
                disabled={resyncMutation.isPending}
                onClick={() => resyncMutation.mutate()}
                size="sm"
                variant="outline"
              >
                {resyncMutation.isPending ? 'Syncing...' : 'Sync Deployments'}
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
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Analysis Results</CardTitle>
        </CardHeader>
        <CardContent>
          {reportQuery.isPending && (
            <p className="text-tertiary text-sm">Loading analysis report...</p>
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
          {analyzeMutation.isPending && (
            <p className="text-tertiary text-sm">Running analysis...</p>
          )}
          {report && results.length === 0 && !analyzeMutation.isPending && (
            <p className="text-tertiary text-sm">
              No analysis plugins reported findings for this project.
            </p>
          )}
          {report && results.length > 0 && (
            <div className="space-y-4">
              <StatusSection results={results} status="fail" />
              <StatusSection results={results} status="warn" />
              <StatusSection results={results} status="pass" />
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function ResultPanel({ result }: { result: AnalysisResult }) {
  const startOpen = result.status !== 'pass'
  return (
    <Collapsible defaultOpen={startOpen}>
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
  results,
  status,
}: {
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
        <ResultPanel key={`${r.plugin_slug}:${r.slug}`} result={r} />
      ))}
    </div>
  )
}
