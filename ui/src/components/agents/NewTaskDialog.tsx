import { type ReactNode, useEffect, useMemo, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronRight,
  ChevronsUpDown,
  Clock,
  Link as LinkIcon,
  Play,
  Plus,
  Search,
  UserRound,
  X,
} from 'lucide-react'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import {
  createTicket,
  type DynamicFieldSchema,
  type DynamicSchema,
  getProjectsSlim,
  getTicketSchema,
  listTickets,
  reassignTicket,
  setTicketParent,
  suggestTicketSubject,
} from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DynamicFormFields,
  requiredBlueprintFields,
  validateDynamicFields,
} from '@/components/ui/dynamic-fields'
import { EntityIcon } from '@/components/ui/entity-icon'
import { Input } from '@/components/ui/input'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { RequiredAsterisk } from '@/components/ui/required-asterisk'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import { Textarea } from '@/components/ui/textarea'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAuth } from '@/hooks/useAuth'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useHasPermission } from '@/hooks/useHasPermission'
import { useTeams } from '@/hooks/useOrgResources'
import { queryKeys } from '@/lib/queryKeys'
import { cn } from '@/lib/utils'
import type { Agent, TicketListItem, TicketType } from '@/types'

import { useAgentList } from './agentQueries'
import { ticketsPath } from './agentsNav'
import { detectSource, titleFrom } from './newTask'
import { type Priority, PriorityPicker } from './priority'
import { statusLabel, statusVariant } from './taskEvents'
import { errorMessage } from './taskQueries'
import {
  LabelInput,
  PersonPicker,
  roleErrors,
  type RoleRow,
  RolesEditor,
  rolesOf,
  TeamPicker,
  TypePicker,
  usePeople,
} from './ticketAttributes'
import { useStoredState } from './useStoredState'

const PROJECTS_SHOWN = 6
const RECENT_AGENTS = 3
/** The pause in typing before a model writes the subject. */
const SUBJECT_DELAY_MS = 800
/** A shorter description keeps its first line as the subject. */
const SUBJECT_MIN_LENGTH = 20
/** `SUBJECT_INPUT_LENGTH` of the API: what the model reads. */
const SUBJECT_INPUT = 8000
const TICKETS_SHOWN = 8

type Prerequisite = TicketListItem & { gates: boolean }

/**
 * Hand a piece of work to an agent or a person (ADR 0028), and open the
 * ticket. A runner starts a queued ticket for its agent; a person ticket
 * starts open. `agent` selects an agent first (the Run button of an
 * agent).
 */
export function NewTaskDialog({
  agent,
  isOpen,
  onClose,
}: {
  agent?: Agent
  isOpen: boolean
  onClose: () => void
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { selectedOrganization } = useOrganization()
  const { user } = useAuth()
  const me = user?.email ?? ''
  const orgSlug = agent?.organization.slug ?? selectedOrganization?.slug ?? ''
  const canManage = useHasPermission('ticket:manage', orgSlug)
  const { isError: peopleError, nameOf, people } = usePeople(orgSlug)
  const [description, setDescription] = useState('')
  const [subject, setSubject] = useState<null | string>(null)
  const [kind, setKind] = useState<'agent' | 'person'>('agent')
  const [agentSlug, setAgentSlug] = useState('')
  const [assignee, setAssignee] = useState('')
  const [type, setType] = useState<TicketType>('task')
  const [priority, setPriority] = useState<Priority>('normal')
  const [due, setDue] = useState('')
  const [projectIds, setProjectIds] = useState<string[]>([])
  const [labels, setLabels] = useState<string[]>([])
  const [owner, setOwner] = useState('')
  const [team, setTeam] = useState('')
  const [fieldValues, setFieldValues] = useState<Record<string, unknown>>({})
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [roles, setRoles] = useState<RoleRow[]>([])
  const [parent, setParent] = useState<null | TicketListItem>(null)
  const [requires, setRequires] = useState<Prerequisite[]>([])
  const [recent, setRecent] = useStoredState<string[]>(
    'imbi.tickets.recentAgents',
    [],
    (raw) =>
      Array.isArray(raw) && raw.every((s) => typeof s === 'string')
        ? raw
        : undefined,
  )

  useEffect(() => {
    if (!isOpen) return
    setDescription('')
    setSubject(null)
    setKind('agent')
    setAgentSlug(agent?.slug ?? '')
    setAssignee('')
    setType('task')
    setPriority('normal')
    setDue('')
    setProjectIds([])
    setLabels([])
    setOwner('')
    setTeam('')
    setFieldValues({})
    setFieldErrors({})
    setRoles([])
    setParent(null)
    setRequires([])
  }, [agent, isOpen])

  // The Run button of an agent keeps its agent.
  const { data: agentList = [] } = useAgentList(
    isOpen && !agent ? orgSlug : undefined,
  )
  const agents = useMemo(
    () =>
      agent
        ? [agent]
        : agentList
            .filter((a) => a.enabled)
            .sort((a, b) => a.name.localeCompare(b.name)),
    [agent, agentList],
  )

  // A model writes the subject once the person stops typing; the first
  // line stands in until it answers, and when it cannot.
  const draft = useDebouncedValue(description.trim(), SUBJECT_DELAY_MS)
  // The API reads only the start of a long description, so an edit
  // after it asks for nothing new.
  const input = draft.slice(0, SUBJECT_INPUT)
  const suggestion = useQuery({
    enabled: isOpen && subject === null && input.length >= SUBJECT_MIN_LENGTH,
    queryFn: ({ signal }) => suggestTicketSubject(orgSlug, input, signal),
    queryKey: queryKeys.ticketSubject(orgSlug, input),
    retry: false,
    staleTime: Infinity,
  })
  const written =
    draft === description.trim() && !suggestion.data?.degraded
      ? suggestion.data?.subject
      : undefined
  const title =
    subject ?? written ?? (description.trim() ? titleFrom(description) : '')
  const subjectTag =
    subject === null && title
      ? suggestion.isFetching
        ? 'Writing…'
        : written
          ? 'AI'
          : 'Auto'
      : undefined
  const source = detectSource(description)
  const person = kind === 'person'
  const chosenAgent = agents.find((a) => a.slug === agentSlug)
  const assigneeName = person ? nameOf(assignee) : chosenAgent?.name
  const heldOn = requires.filter((r) => r.gates && r.status !== 'closed')
  const ready =
    !!description.trim() &&
    !!title.trim() &&
    (person ? !!assignee : !!agentSlug)
  const ownerEmail = owner || me
  const roleMap = rolesOf(roles)
  const { data: teams = [] } = useTeams(orgSlug, { enabled: isOpen })
  const schemaParams = { label: labels, priority, type }
  const schema = useQuery({
    enabled: isOpen && !!orgSlug,
    queryFn: ({ signal }) => getTicketSchema(orgSlug, schemaParams, signal),
    queryKey: queryKeys.ticketSchema(orgSlug, schemaParams),
  })

  const create = useMutation({
    mutationFn: async () => {
      const task = await createTicket(orgSlug, {
        ...(person
          ? { assignee, assignee_kind: 'person' }
          : { agent_slug: agentSlug, assignee_kind: 'agent' }),
        custom_fields: customFields,
        description: description.trim(),
        due_date: due || null,
        labels,
        priority,
        project_ids: projectIds,
        requires: requires.map(({ gates, short_id }) => ({ gates, short_id })),
        roles: roleMap,
        team: team || null,
        title: title.trim(),
        type,
      })
      // The ticket is made; a failure here only warns, and it opens.
      // Each step runs, also when the other fails.
      const warn = (err: unknown) => {
        toast.error(
          `${task.short_id} was created, but: ${errorMessage(err as Error)}`,
        )
      }
      if (parent)
        await setTicketParent(orgSlug, task.short_id, parent.short_id).catch(
          warn,
        )
      if (owner && owner !== me)
        await reassignTicket(orgSlug, task.short_id, owner).catch(warn)
      return task
    },
    onSuccess: (task) => {
      if (!person)
        setRecent((r) =>
          [agentSlug, ...r.filter((s) => s !== agentSlug)].slice(
            0,
            RECENT_AGENTS,
          ),
        )
      void queryClient.invalidateQueries({
        queryKey: queryKeys.tickets(orgSlug),
      })
      onClose()
      navigate(ticketsPath(orgSlug, task.short_id))
    },
  })
  const { reset } = create
  // A reopened dialog shows no error from the last attempt.
  useEffect(() => {
    if (isOpen) reset()
  }, [isOpen, reset])
  const canSubmit =
    ready && roleErrors(roles).every((e) => !e) && !create.isPending
  // The required fields with no default, and each field that the API
  // said is missing (the schema here can be older than the API's).
  const issues = customFieldIssues(create.error)
  const required = requiredBlueprintFields(schema.data?.sections)
  const fieldSchema: DynamicSchema = {
    properties: { ...required.properties, ...issues.missing },
    required: [...(required.required ?? []), ...Object.keys(issues.missing)],
  }
  // An unchecked required boolean means false, not "not set".
  const customFields = Object.fromEntries(
    Object.entries(fieldSchema.properties)
      .map(([key, field]) => [
        key,
        fieldValues[key] ?? (field.type === 'boolean' ? false : undefined),
      ])
      .filter(([, value]) => value !== undefined),
  )
  const submit = () => {
    const errors = validateDynamicFields(fieldSchema, customFields)
    setFieldErrors(errors)
    if (canSubmit && Object.keys(errors).length === 0) create.mutate()
  }

  const relationsSummary =
    [
      parent && `Parent ${parent.short_id}`,
      requires.length > 0 &&
        `${requires.length} ${requires.length === 1 ? 'prerequisite' : 'prerequisites'}`,
      heldOn.length > 0 && 'starts held',
    ]
      .filter(Boolean)
      .join(' · ') || 'Parent, prerequisites'
  const roleNames = Object.keys(roleMap)

  return (
    <Dialog
      onOpenChange={(o) => !o && !create.isPending && onClose()}
      open={isOpen}
    >
      <DialogContent className="max-h-[calc(100vh-48px)] max-w-160 gap-0 overflow-hidden p-0">
        <div className="border-tertiary shrink-0 border-b px-5 py-3.5 pr-12">
          <DialogTitle className="text-lg font-medium">New ticket</DialogTitle>
          <DialogDescription className="sr-only">
            Hand a piece of work to an agent or a person.
          </DialogDescription>
        </div>
        <form
          className="flex min-h-0 flex-1 flex-col gap-3.5 overflow-y-auto px-5 py-4"
          id="new-ticket"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <Field
            hint="Written from the description. Type to override."
            htmlFor="nt-subject"
            label="Subject"
            tag={subjectTag}
          >
            <Input
              className="h-9"
              id="nt-subject"
              onChange={(e) => setSubject(e.target.value)}
              placeholder="Fills in as you describe the work"
              value={title}
            />
          </Field>

          <Field htmlFor="nt-description" label="Describe the work" required>
            <Textarea
              className="h-23 resize-none"
              id="nt-description"
              onChange={(e) => setDescription(e.target.value)}
              placeholder="The outcome you want. Paste a Sentry issue, pull request, or Slack thread link to use it as the source."
              value={description}
            />
            {source && (
              <a
                className="text-tertiary flex min-w-0 items-center gap-1.5 text-[12.5px]"
                href={source.url}
                rel="noreferrer"
                target="_blank"
              >
                <LinkIcon aria-hidden className="size-3.25 shrink-0" />
                Source
                <span className="text-info truncate">{source.label}</span>
              </a>
            )}
          </Field>

          <Field label="Assign to" labelId="nt-assign" required>
            <div className="flex items-center gap-2">
              {!agent && (
                <SegmentedControl
                  ariaLabel="Assignee kind"
                  onValueChange={(v) => setKind(v as 'agent' | 'person')}
                  value={kind}
                >
                  <SegmentedControlItem value="agent">
                    Agent
                  </SegmentedControlItem>
                  <SegmentedControlItem value="person">
                    Person
                  </SegmentedControlItem>
                </SegmentedControl>
              )}
              {person ? (
                <PersonPicker
                  ariaLabel="Assignee"
                  loadError={peopleError}
                  onChange={setAssignee}
                  people={people}
                  value={assignee}
                />
              ) : (
                <AgentPicker
                  agents={agents}
                  onChange={setAgentSlug}
                  recent={recent}
                  value={agentSlug}
                />
              )}
            </div>
            {person && (
              <span className="text-tertiary text-[12.5px]">
                Starts open. Person tickets have no agent, budget, or run
                controls.
              </span>
            )}
          </Field>

          <div className="grid grid-cols-[auto_auto_minmax(0,1fr)] items-start gap-3 max-sm:grid-cols-1">
            <Field label="Type">
              <TypePicker onChange={setType} value={type} />
            </Field>
            <Field label="Priority">
              <PriorityPicker onChange={setPriority} value={priority} />
            </Field>
            <Field htmlFor="nt-due" label="Due">
              <Input
                className={cn('h-8.5 text-[13.5px]', !due && 'text-tertiary')}
                id="nt-due"
                onChange={(e) => setDue(e.target.value)}
                type="date"
                value={due}
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 items-start gap-3 max-sm:grid-cols-1">
            <Field htmlFor="nt-projects" label="Projects">
              <ProjectInput
                id="nt-projects"
                isOpen={isOpen}
                onChange={setProjectIds}
                orgSlug={orgSlug}
                value={projectIds}
              />
            </Field>
            <Field htmlFor="nt-labels" label="Labels">
              <LabelInput
                id="nt-labels"
                onChange={setLabels}
                orgSlug={orgSlug}
                value={labels}
              />
            </Field>
          </div>

          <DynamicFormFields
            data={fieldValues}
            errors={{ ...issues.errors, ...fieldErrors }}
            onChange={(key, value) =>
              setFieldValues((prev) => ({ ...prev, [key]: value }))
            }
            schema={fieldSchema}
          />

          <div className="border-tertiary rounded-md border">
            <Disclosure
              label="Owner"
              summary={
                ownerEmail === me
                  ? `You${user?.display_name ? ` (${user.display_name})` : ''}`
                  : nameOf(ownerEmail)
              }
            >
              <PersonPicker
                ariaLabel="Owner"
                disabled={!canManage}
                loadError={peopleError}
                onChange={setOwner}
                people={people}
                value={ownerEmail}
              />
              <span className="text-tertiary text-[12.5px]">
                Accountable for the outcome. Defaults to you; can differ from
                the assignee.
                {!canManage && ' Another owner needs ticket:manage.'}
              </span>
            </Disclosure>
            <Disclosure
              label="Team"
              summary={teams.find((t) => t.slug === team)?.name ?? 'None'}
            >
              <TeamPicker onChange={setTeam} orgSlug={orgSlug} value={team} />
              <span className="text-tertiary text-[12.5px]">
                The team that owns the work.
              </span>
            </Disclosure>
            <Disclosure
              label="Roles"
              summary={
                roleNames.length
                  ? roleNames.join(', ')
                  : 'Reviewer, QA, approver…'
              }
            >
              <RolesEditor
                loadError={peopleError}
                onChange={setRoles}
                people={people}
                rows={roles}
              />
              <span className="text-tertiary text-[12.5px]">
                Workflows read roles and can hand the ticket to the person in a
                role.
              </span>
            </Disclosure>
            <Disclosure label="Relations" summary={relationsSummary}>
              <ParentField
                onChange={setParent}
                orgSlug={orgSlug}
                parent={parent}
                taken={requires.map((r) => r.short_id)}
              />
              <PrerequisitesField
                heldOn={heldOn.map((r) => r.short_id)}
                onChange={setRequires}
                orgSlug={orgSlug}
                taken={parent ? [parent.short_id] : []}
                value={requires}
              />
            </Disclosure>
          </div>

          {create.error && (
            <p className="text-danger text-sm" role="alert">
              {errorMessage(create.error)}
            </p>
          )}
        </form>
        <div className="border-tertiary bg-secondary flex shrink-0 items-center gap-2.5 border-t px-5 py-3">
          <FooterHint
            assigneeName={assigneeName}
            heldOn={heldOn.map((r) => r.short_id)}
            person={person}
            ready={ready}
          />
          <Button
            className="ml-auto"
            disabled={create.isPending}
            onClick={onClose}
            type="button"
            variant="outline"
          >
            Cancel
          </Button>
          <Button disabled={!canSubmit} form="new-ticket" type="submit">
            <Plus className="size-3.5" />
            Create ticket
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** The agent of a ticket: recently used ones first, then all. */
function AgentPicker({
  agents,
  onChange,
  recent,
  value,
}: {
  agents: Agent[]
  onChange: (slug: string) => void
  recent: string[]
  value: string
}) {
  const [open, setOpen] = useState(false)
  const picked = agents.find((a) => a.slug === value)
  const recents = recent
    .map((slug) => agents.find((a) => a.slug === slug))
    .filter((a): a is Agent => !!a)
  const others = agents.filter((a) => !recent.includes(a.slug))
  const row = (a: Agent) => (
    <CommandItem
      key={a.slug}
      onSelect={() => {
        onChange(a.slug)
        setOpen(false)
      }}
      value={`${a.name} ${a.slug} ${a.description ?? ''}`}
    >
      <AgentRow agent={a} />
    </CommandItem>
  )
  return (
    <Popover onOpenChange={setOpen} open={open}>
      <PopoverTrigger asChild>
        <button
          aria-expanded={open}
          aria-haspopup="listbox"
          aria-labelledby="nt-assign"
          className="border-input bg-primary flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md border px-2.5 text-left"
          type="button"
        >
          {picked ? (
            <AgentRow agent={picked} />
          ) : (
            <>
              <Search aria-hidden className="text-tertiary size-3.5" />
              <span className="text-tertiary flex-1 text-sm">
                {agents.length ? 'Choose an agent' : 'No enabled agents'}
              </span>
            </>
          )}
          <ChevronsUpDown
            aria-hidden
            className="text-tertiary size-3.5 shrink-0"
          />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-(--radix-popover-trigger-width) min-w-100 p-0"
      >
        <Command>
          <CommandInput placeholder="Search agents by name or purpose" />
          <CommandList className="max-h-75">
            <CommandEmpty>No agents match.</CommandEmpty>
            {recents.length > 0 && (
              <CommandGroup heading="Recent">{recents.map(row)}</CommandGroup>
            )}
            <CommandGroup heading="All agents">{others.map(row)}</CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

function AgentRow({ agent }: { agent: Agent }) {
  return (
    <span className="flex min-w-0 flex-1 items-center gap-2">
      <span className="bg-secondary text-secondary flex size-5.5 shrink-0 items-center justify-center rounded-sm text-[10px] font-semibold">
        {agent.icon ? (
          <EntityIcon className="size-3.5" icon={agent.icon} />
        ) : (
          agent.name.slice(0, 2).toUpperCase()
        )}
      </span>
      <span className="text-sm font-medium whitespace-nowrap">
        {agent.name}
      </span>
      <span className="text-tertiary font-mono text-xs">v{agent.version}</span>
      {agent.description && (
        <span className="text-tertiary min-w-0 flex-1 truncate text-[13px]">
          {agent.description}
        </span>
      )}
    </span>
  )
}

/**
 * The field errors of a `custom_fields_invalid` 422, and the property of
 * each missing field, so that the dialog can ask for it.
 */
function customFieldIssues(error: Error | null): {
  errors: Record<string, string>
  missing: Record<string, DynamicFieldSchema>
} {
  const detail =
    error instanceof ApiError
      ? (
          error.data as
            | undefined
            | {
                detail?: {
                  error?: string
                  invalid?: { field: string; message: string }[]
                  missing?: (DynamicFieldSchema & { field: string })[]
                }
              }
        )?.detail
      : undefined
  if (detail?.error !== 'custom_fields_invalid')
    return { errors: {}, missing: {} }
  const errors: Record<string, string> = {}
  const missing: Record<string, DynamicFieldSchema> = {}
  for (const { field, ...prop } of detail.missing ?? []) {
    errors[field] = 'Required'
    missing[field] = {
      description: prop.description ?? undefined,
      enum: prop.enum ?? undefined,
      format: prop.format ?? undefined,
      title: prop.title ?? undefined,
      type: prop.type ?? undefined,
    }
  }
  for (const { field, message } of detail.invalid ?? []) errors[field] = message
  return { errors, missing }
}

/** A section that starts closed and says what it holds when closed. */
function Disclosure({
  children,
  label,
  summary,
}: {
  children: ReactNode
  label: string
  summary: string
}) {
  return (
    <Collapsible className="group border-tertiary border-b last:border-b-0">
      <CollapsibleTrigger className="flex h-9 w-full items-center gap-2 px-3 text-left">
        <ChevronRight
          aria-hidden
          className="text-tertiary size-3.5 transition-transform group-data-[state=open]:rotate-90"
        />
        <span className="text-secondary text-[13px] font-medium">{label}</span>
        <span className="text-tertiary ml-auto min-w-0 truncate text-[13px]">
          {summary}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent className="flex flex-col gap-3 pr-3 pb-3 pl-8.5">
        {children}
      </CollapsibleContent>
    </Collapsible>
  )
}

function Field({
  children,
  hint,
  htmlFor,
  label,
  labelId,
  required,
  tag,
}: {
  children: ReactNode
  hint?: string
  htmlFor?: string
  label: string
  labelId?: string
  required?: boolean
  tag?: string
}) {
  const text = (
    <>
      {label}
      {required && (
        <>
          {' '}
          <RequiredAsterisk />
        </>
      )}
    </>
  )
  const className = 'text-[13px] font-medium text-secondary'
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <div className="flex items-center gap-2">
        {htmlFor ? (
          <label className={className} htmlFor={htmlFor}>
            {text}
          </label>
        ) : (
          <span className={className} id={labelId}>
            {text}
          </span>
        )}
        {tag && (
          <span className="bg-secondary text-secondary inline-flex h-4.5 items-center rounded-sm px-1.5 text-[11.5px] font-medium">
            {tag}
          </span>
        )}
        {hint && (
          <span className="text-tertiary ml-auto text-[12.5px] max-sm:hidden">
            {hint}
          </span>
        )}
      </div>
      {children}
    </div>
  )
}

/** What happens on create, or what the dialog still needs. */
function FooterHint({
  assigneeName,
  heldOn,
  person,
  ready,
}: {
  assigneeName?: string
  heldOn: string[]
  person: boolean
  ready: boolean
}) {
  if (!ready)
    return (
      <span className="text-tertiary text-[13px]">
        Needs a description and an assignee.
      </span>
    )
  if (heldOn.length)
    return (
      <span className="text-warning flex min-w-0 items-center gap-1.5 text-[13px]">
        <Clock aria-hidden className="size-3.25 shrink-0" />
        <span className="truncate">
          {person
            ? `Assigns to ${assigneeName}, starts held`
            : `Starts held: waits on ${heldOn.join(', ')}`}
        </span>
      </span>
    )
  const Icon = person ? UserRound : Play
  return (
    <span className="text-secondary flex min-w-0 items-center gap-1.5 text-[13px]">
      <Icon
        aria-hidden
        className={cn('size-3.25 shrink-0', !person && 'text-success')}
      />
      <span className="truncate">
        {person ? 'Assigns to' : 'Runs now with'} {assigneeName}
      </span>
    </span>
  )
}

function ParentField({
  onChange,
  orgSlug,
  parent,
  taken,
}: {
  onChange: (parent: null | TicketListItem) => void
  orgSlug: string
  parent: null | TicketListItem
  taken: string[]
}) {
  return (
    <Field hint="Optional. Closed parents are allowed." label="Parent">
      {parent ? (
        <span className="border-tertiary flex h-9 items-center rounded-md border px-1.5">
          <span className="bg-secondary flex h-6 min-w-0 items-center gap-1.5 rounded-sm pr-1 pl-2 text-[13px]">
            <span className="text-secondary font-mono text-[12.5px]">
              {parent.short_id}
            </span>
            <span className="truncate">{parent.title}</span>
            <button
              aria-label="Remove parent"
              className="text-tertiary hover:text-primary flex size-4.5 shrink-0 items-center justify-center rounded"
              onClick={() => onChange(null)}
              type="button"
            >
              <X className="size-3" />
            </button>
          </span>
        </span>
      ) : (
        <TicketSearch
          ariaLabel="Parent"
          exclude={taken}
          onPick={onChange}
          orgSlug={orgSlug}
          placeholder="Search tickets by ID or title"
        />
      )}
    </Field>
  )
}

function PrerequisitesField({
  heldOn,
  onChange,
  orgSlug,
  taken,
  value,
}: {
  heldOn: string[]
  onChange: (value: Prerequisite[]) => void
  orgSlug: string
  taken: string[]
  value: Prerequisite[]
}) {
  return (
    <Field hint="Gating: waits until it closes as done" label="Prerequisites">
      <div className="border-tertiary rounded-md border">
        {value.map((r) => (
          <div
            className="border-tertiary flex h-9 items-center gap-2 border-b pr-1.5 pl-2.5"
            key={r.short_id}
          >
            <span className="text-secondary font-mono text-[12.5px]">
              {r.short_id}
            </span>
            <span className="min-w-0 flex-1 truncate text-[13.5px]">
              {r.title}
            </span>
            <Badge className="shrink-0 py-0" variant={statusVariant(r)}>
              {statusLabel(r)}
            </Badge>
            <label className="text-secondary flex items-center gap-1.5 px-1 text-[13px]">
              <Checkbox
                aria-label={`Gating for ${r.short_id}`}
                checked={r.gates}
                onCheckedChange={(v) =>
                  onChange(
                    value.map((x) =>
                      x.short_id === r.short_id
                        ? { ...x, gates: v === true }
                        : x,
                    ),
                  )
                }
              />
              Gating
            </label>
            <button
              aria-label={`Remove ${r.short_id}`}
              className="text-tertiary hover:text-primary flex size-6 items-center justify-center rounded"
              onClick={() =>
                onChange(value.filter((x) => x.short_id !== r.short_id))
              }
              type="button"
            >
              <X className="size-3.25" />
            </button>
          </div>
        ))}
        <TicketSearch
          ariaLabel="Add prerequisite"
          bare
          exclude={[...value.map((r) => r.short_id), ...taken]}
          onPick={(t) => onChange([...value, { ...t, gates: true }])}
          orgSlug={orgSlug}
          placeholder="Add a prerequisite ticket"
        />
      </div>
      {heldOn.length > 0 && (
        <div
          className="bg-warning text-warning flex items-center gap-2 rounded-md px-2.5 py-2 text-[13px]"
          role="status"
        >
          <Clock aria-hidden className="size-3.5" />
          <span>
            Starts held: waits on{' '}
            <span className="font-mono">{heldOn.join(', ')}</span>.
          </span>
        </div>
      )}
    </Field>
  )
}

/** Projects as chips and a search that adds one. */
function ProjectInput({
  id,
  isOpen,
  onChange,
  orgSlug,
  value,
}: {
  id: string
  isOpen: boolean
  onChange: (ids: string[]) => void
  orgSlug: string
  value: string[]
}) {
  const [query, setQuery] = useState('')
  const [focused, setFocused] = useState(false)
  const { data: projectList = [] } = useQuery({
    enabled: !!orgSlug && isOpen,
    queryFn: ({ signal }) => getProjectsSlim(orgSlug, signal),
    queryKey: ['projects', orgSlug, 'slim'],
  })
  const selected = value
    .map((pid) => projectList.find((p) => p.id === pid))
    .filter((p) => !!p)
  const q = query.trim().toLowerCase()
  const matches = projectList
    .filter(
      (p) => !p.archived && !value.includes(p.id) && (!q || p.slug.includes(q)),
    )
    .sort((a, b) => a.slug.localeCompare(b.slug))
    .slice(0, PROJECTS_SHOWN)
  const showMenu = focused && matches.length > 0
  return (
    <div className="relative">
      <div className="border-input bg-primary flex min-h-9 flex-wrap items-center gap-1 rounded-md border px-1.5 py-1">
        {selected.map((p) => (
          <span
            className="bg-secondary inline-flex h-6 items-center gap-1 rounded-sm pr-1 pl-2 font-mono text-[12.5px]"
            key={p.id}
          >
            {p.slug}
            <button
              aria-label={`Remove project ${p.slug}`}
              className="text-tertiary hover:text-primary flex size-4.5 items-center justify-center rounded"
              onClick={() => onChange(value.filter((x) => x !== p.id))}
              type="button"
            >
              <X className="size-3" />
            </button>
          </span>
        ))}
        <input
          aria-autocomplete="list"
          aria-expanded={showMenu}
          className="h-6.5 min-w-20 flex-1 bg-transparent px-1 text-sm outline-none"
          id={id}
          onBlur={() => setFocused(false)}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setFocused(true)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && matches[0]) {
              e.preventDefault()
              onChange([...value, matches[0].id])
              setQuery('')
            }
          }}
          placeholder={selected.length ? 'Add project' : 'Search projects'}
          role="combobox"
          value={query}
        />
      </div>
      {showMenu && (
        <div
          aria-label="Projects"
          className="border-secondary bg-primary absolute inset-x-0 top-full z-50 mt-1 overflow-hidden rounded-md border shadow-md"
          role="listbox"
        >
          {matches.map((p, i) => (
            <div
              aria-selected={i === 0}
              className="hover:bg-secondary flex h-8.5 cursor-pointer items-center gap-2 px-3"
              key={p.id}
              // Keep focus in the input.
              onMouseDown={(e) => {
                e.preventDefault()
                onChange([...value, p.id])
                setQuery('')
              }}
              role="option"
            >
              <span className="font-mono text-[12.5px]">{p.slug}</span>
              <span className="text-tertiary ml-auto text-[11.5px]">
                {p.project_types[0]?.name}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Find a ticket of the org by short id or title. */
function TicketSearch({
  ariaLabel,
  bare,
  exclude,
  onPick,
  orgSlug,
  placeholder,
}: {
  ariaLabel: string
  bare?: boolean
  exclude: string[]
  onPick: (ticket: TicketListItem) => void
  orgSlug: string
  placeholder: string
}) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const q = useDebouncedValue(text.trim(), 200)
  const { data = [] } = useQuery({
    enabled: open && !!orgSlug,
    queryFn: ({ signal }) =>
      listTickets(orgSlug, { limit: TICKETS_SHOWN, q: q || undefined }, signal),
    queryKey: queryKeys.tickets(orgSlug, { limit: TICKETS_SHOWN, q }),
  })
  const found = data.filter((t) => !exclude.includes(t.short_id))
  const Icon = bare ? Plus : Search
  return (
    <Popover onOpenChange={setOpen} open={open}>
      <PopoverTrigger asChild>
        <button
          aria-label={ariaLabel}
          className={cn(
            'flex h-9 w-full items-center gap-2 px-2.5 text-left text-sm text-tertiary',
            !bare && 'rounded-md border border-input',
          )}
          type="button"
        >
          <Icon aria-hidden className="size-3.5" />
          {placeholder}
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-(--radix-popover-trigger-width) p-0"
      >
        <Command shouldFilter={false}>
          <CommandInput
            onValueChange={setText}
            placeholder={placeholder}
            value={text}
          />
          <CommandList>
            <CommandEmpty>No tickets match.</CommandEmpty>
            <CommandGroup>
              {found.map((t) => (
                <CommandItem
                  key={t.short_id}
                  onSelect={() => {
                    onPick(t)
                    setText('')
                    setOpen(false)
                  }}
                  value={t.short_id}
                >
                  <span className="text-secondary font-mono text-xs">
                    {t.short_id}
                  </span>
                  <span className="min-w-0 flex-1 truncate">{t.title}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
