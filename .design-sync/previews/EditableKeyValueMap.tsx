import { EditableKeyValueMap, useEditableKeyValueMap } from 'imbi-ui'
import { BookOpen, Github, type LucideIcon, Radar, Siren } from 'lucide-react'

type LinkDef = { icon: LucideIcon; name: string; url_template: string }

const LINK_DEFS: Record<string, LinkDef> = {
  docs: {
    icon: BookOpen,
    name: 'Docs',
    url_template: 'https://docs.example.com/...',
  },
  github: {
    icon: Github,
    name: 'GitHub',
    url_template: 'https://github.com/org/repo',
  },
  pagerduty: {
    icon: Siren,
    name: 'PagerDuty',
    url_template: 'https://example.pagerduty.com/service-directory/...',
  },
  sentry: {
    icon: Radar,
    name: 'Sentry',
    url_template: 'https://sentry.io/organizations/...',
  },
}

// The app wires onPatch to an API mutation; here it resolves at once.
const useMapState = (serverMap: Record<string, string>) =>
  useEditableKeyValueMap<string>({ onPatch: async () => {}, serverMap })

const LINKS = {
  github: 'https://github.com/aweber-imbi/imbi',
  sentry: 'https://sentry.io/organizations/aweber/projects/imbi-api/',
}
const IDENTIFIERS = {
  pagerduty_service: 'P4X2K9Q',
  sentry_project: 'imbi-api',
  sonarqube_key: 'aweber-imbi_imbi',
}
const EMPTY = {}

const linkProps = {
  deleteDialogDescription: 'This will remove the link from the project.',
  getDeleteDialogTitle: (slug: null | string) =>
    slug ? `Remove ${LINK_DEFS[slug]?.name ?? 'link'}?` : 'Remove link?',
  getNewValuePlaceholder: (slug: null | string) =>
    (slug && LINK_DEFS[slug]?.url_template) || 'https://...',
  getRemoveAriaLabel: (slug: string) =>
    `Remove ${LINK_DEFS[slug]?.name ?? 'link'} link`,
  getValuePlaceholder: (slug: string) =>
    LINK_DEFS[slug]?.url_template || 'https://...',
  newKeyPlaceholder: 'Pick Link Type to Add',
  renderKeyLabel: (slug: string) => {
    const { icon: Icon, name } = LINK_DEFS[slug]
    return (
      <div className="text-secondary flex w-[15%] shrink-0 items-center gap-2">
        <Icon className="size-4 shrink-0" />
        <span className="truncate text-sm">{name}</span>
      </div>
    )
  },
  renderSelectItem: (slug: string) => {
    const { icon: Icon, name } = LINK_DEFS[slug]
    return (
      <span className="flex items-center gap-2">
        <Icon className="size-4" />
        {name}
      </span>
    )
  },
  renderSelectTrigger: (slug: string) => {
    const { icon: Icon, name } = LINK_DEFS[slug]
    return (
      <div className="text-secondary flex min-w-0 items-center gap-2">
        <Icon className="size-4 shrink-0" />
        <span className="truncate">{name}</span>
      </div>
    )
  },
  title: 'Links',
  valueInputType: 'url' as const,
}

export const ProjectLinks = () => {
  const state = useMapState(LINKS)
  return (
    <div className="w-full">
      <EditableKeyValueMap
        {...linkProps}
        state={state}
        unassignedKeys={['docs', 'pagerduty']}
        visibleKeys={['github', 'sentry']}
      />
    </div>
  )
}

export const Identifiers = () => {
  const state = useMapState(IDENTIFIERS)
  const names: Record<string, string> = {
    pagerduty_service: 'PagerDuty',
    sentry_project: 'Sentry',
    sonarqube_key: 'SonarQube',
  }
  return (
    <div className="w-full">
      <EditableKeyValueMap
        deleteDialogDescription="This will remove the identifier from the project."
        getDeleteDialogTitle={(k) =>
          k ? `Remove ${names[k] ?? 'identifier'}?` : 'Remove identifier?'
        }
        getNewValuePlaceholder={() => 'Identifier'}
        getRemoveAriaLabel={(k) => `Remove ${names[k] ?? k} identifier`}
        getValuePlaceholder={(k) => `${names[k] ?? k} identifier`}
        newKeyPlaceholder="Add Identifier"
        renderKeyLabel={(k) => (
          <span className="text-secondary w-[15%] shrink-0 truncate text-sm">
            {names[k] ?? k}
          </span>
        )}
        renderSelectItem={(k) => names[k] ?? k}
        renderSelectTrigger={(k) => (
          <span className="truncate">{names[k] ?? k}</span>
        )}
        state={state}
        title="Identifiers"
        unassignedKeys={[]}
        valueInputClassName="font-mono"
        visibleKeys={['pagerduty_service', 'sentry_project', 'sonarqube_key']}
      />
    </div>
  )
}

export const EmptyWithAddRow = () => {
  const state = useMapState(EMPTY)
  return (
    <div className="w-full">
      <EditableKeyValueMap
        {...linkProps}
        state={state}
        unassignedKeys={['github', 'docs', 'sentry', 'pagerduty']}
        visibleKeys={[]}
      />
    </div>
  )
}
