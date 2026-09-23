import {
  Button,
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from 'imbi-ui'
import { AlertTriangle, CheckCircle2, ChevronDown, XCircle } from 'lucide-react'

export const DoctorCheckOpen = () => (
  <div className="w-full max-w-xl">
    <Collapsible defaultOpen>
      <CollapsibleTrigger className="bg-danger/10 border-danger/40 flex w-full items-center gap-3 rounded-md border px-3 py-2 text-left text-sm">
        <XCircle className="text-danger size-4" />
        <span className="flex-1 font-medium">Dockerfile base image is pinned</span>
        <span className="text-danger text-xs uppercase">Fail</span>
        <span className="text-tertiary font-mono text-xs">github</span>
      </CollapsibleTrigger>
      <CollapsibleContent className="text-secondary px-3 pt-2 pb-3 text-sm">
        The base image uses the floating tag python:3-slim. Pin it to a
        specific version such as python:3.14-slim so builds stay reproducible.
      </CollapsibleContent>
    </Collapsible>
  </div>
)

export const DoctorCheckList = () => (
  <div className="flex w-full max-w-xl flex-col gap-2">
    <Collapsible defaultOpen>
      <CollapsibleTrigger className="bg-warning/10 border-warning/40 flex w-full items-center gap-3 rounded-md border px-3 py-2 text-left text-sm">
        <AlertTriangle className="text-warning size-4" />
        <span className="flex-1 font-medium">CODEOWNERS file is present</span>
        <span className="text-warning text-xs uppercase">Warn</span>
        <span className="text-tertiary font-mono text-xs">github</span>
      </CollapsibleTrigger>
      <CollapsibleContent className="text-secondary px-3 pt-2 pb-3 text-sm">
        No CODEOWNERS file found. Add one so pull requests request review from
        Platform Engineering automatically.
      </CollapsibleContent>
    </Collapsible>
    <Collapsible>
      <CollapsibleTrigger className="bg-success/10 border-success/40 flex w-full items-center gap-3 rounded-md border px-3 py-2 text-left text-sm">
        <CheckCircle2 className="text-success size-4" />
        <span className="flex-1 font-medium">Default branch is protected</span>
        <span className="text-success text-xs uppercase">Pass</span>
        <span className="text-tertiary font-mono text-xs">github</span>
      </CollapsibleTrigger>
      <CollapsibleContent className="text-secondary px-3 pt-2 pb-3 text-sm">
        main requires a pull request and passing checks.
      </CollapsibleContent>
    </Collapsible>
    <Collapsible>
      <CollapsibleTrigger className="bg-success/10 border-success/40 flex w-full items-center gap-3 rounded-md border px-3 py-2 text-left text-sm">
        <CheckCircle2 className="text-success size-4" />
        <span className="flex-1 font-medium">Health check endpoint responds</span>
        <span className="text-success text-xs uppercase">Pass</span>
        <span className="text-tertiary font-mono text-xs">sonarqube</span>
      </CollapsibleTrigger>
      <CollapsibleContent className="text-secondary px-3 pt-2 pb-3 text-sm">
        GET /status returned 200 in 38 ms.
      </CollapsibleContent>
    </Collapsible>
  </div>
)

export const AdvancedSettings = () => (
  <div className="w-96">
    <Collapsible defaultOpen>
      <CollapsibleTrigger asChild>
        <Button className="gap-2" size="sm" variant="ghost">
          <ChevronDown className="size-4" />
          Advanced settings
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="text-secondary mt-2 flex flex-col gap-1 rounded-md border p-3 text-sm">
        <div>Deploy timeout: 15 minutes</div>
        <div>Rollback on failed health check: enabled</div>
      </CollapsibleContent>
    </Collapsible>
  </div>
)
