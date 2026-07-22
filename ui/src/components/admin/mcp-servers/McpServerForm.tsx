import { useState } from 'react'

import { useQueryClient } from '@tanstack/react-query'
import { AlertCircle, KeyRound, Plug, ShieldCheck, Unlock } from 'lucide-react'

import { ApiError } from '@/api/client'
import { testMcpServer, testMcpServerConfig } from '@/api/endpoints'
import { FormHeader } from '@/components/admin/form-header'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RequiredAsterisk } from '@/components/ui/required-asterisk'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { slugify } from '@/lib/utils'
import type {
  MCPServer,
  MCPServerAuthType,
  MCPServerCreate,
  MCPServerTestConfig,
  MCPServerUpdate,
} from '@/types'

import { ConnectionTestPanel } from './ConnectionTestPanel'
import { IgnoredToolsEditor } from './IgnoredToolsEditor'
import { SecretField } from './SecretField'

export type McpServerSaveData =
  | { data: MCPServerCreate; mode: 'create' }
  | { data: MCPServerUpdate; id: string; mode: 'edit' }

interface FormState {
  authType: MCPServerAuthType
  description: string
  enabled: boolean
  icon: string
  ignoredTools: string[]
  name: string
  oauthCleared: boolean
  oauthClientId: string
  oauthEditing: boolean
  oauthScope: string
  oauthTokenUrl: string
  oauthValue: string
  slug: string
  slugTouched: boolean
  staticCleared: boolean
  staticEditing: boolean
  staticHeader: string
  staticValue: string
  timeout: number
  toolPrefix: string
  url: string
  verifySsl: boolean
}

interface McpServerFormProps {
  error?: ApiError<{ detail?: string }> | Error | null
  isLoading?: boolean
  onCancel: () => void
  onSave: (data: McpServerSaveData) => void
  server: MCPServer | null
}

// fallow-ignore-next-line complexity
export function McpServerForm({
  error,
  isLoading = false,
  onCancel,
  onSave,
  server,
}: McpServerFormProps) {
  const isEditing = !!server
  const queryClient = useQueryClient()
  const [s, setS] = useState<FormState>(() => initialState(server))
  const [errors, setErrors] = useState<Record<string, string>>({})
  // Tool names discovered by the last connection test, offered as a
  // dropdown in the ignored-tools picker.
  const [discoveredTools, setDiscoveredTools] = useState<string[]>([])

  const set = (patch: Partial<FormState>) =>
    setS((prev) => ({ ...prev, ...patch }))

  const slugConflict =
    error instanceof ApiError && error.status === 409 ? error : null

  const handleName = (name: string) =>
    set(isEditing || s.slugTouched ? { name } : { name, slug: slugify(name) })

  const handleSave = () => {
    const found = validate(s, server)
    setErrors(found)
    if (Object.keys(found).length > 0) return
    if (isEditing && server) {
      onSave({ data: buildUpdate(s), id: server.id, mode: 'edit' })
    } else {
      onSave({ data: buildCreate(s), mode: 'create' })
    }
  }

  const runTest = async () => {
    if (isEditing && server) {
      const result = await testMcpServer(server.id)
      await queryClient.invalidateQueries({ queryKey: ['mcp-servers'] })
      return result
    }
    return testMcpServerConfig(buildCreate(s) as MCPServerTestConfig)
  }

  const prefix = s.toolPrefix.trim() || s.slug.trim() || '…'

  return (
    <div className="space-y-6">
      <FormHeader
        createLabel="Create Server"
        isEditing={isEditing}
        isLoading={isLoading}
        onCancel={onCancel}
        onSave={handleSave}
        subtitle={
          isEditing
            ? `Configure the ${server.name} MCP server.`
            : 'Connect a streamable-HTTP MCP endpoint the assistant can call.'
        }
        title={isEditing ? `Edit ${server.name}` : 'Add MCP Server'}
      />

      {error && !slugConflict && (
        <ErrorBanner error={error} title="Failed to save MCP server" />
      )}

      {/* Identity */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Identity</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Field error={errors.name} label="Display name" required>
            <Input
              onChange={(e) => handleName(e.target.value)}
              placeholder="GitHub"
              value={s.name}
            />
          </Field>
          <Field
            error={errors.slug ?? slugConflict?.data?.detail}
            help={
              <>
                URL-safe identifier. Used in tool names like{' '}
                <code className="bg-secondary rounded px-1 py-0.5 font-mono">
                  mcp_{prefix}_…
                </code>
                . Changing it later renames every tool this server exposes.
              </>
            }
            label="Slug"
            required
          >
            <Input
              className="font-mono"
              onChange={(e) => set({ slug: e.target.value, slugTouched: true })}
              placeholder="github"
              value={s.slug}
            />
          </Field>
          <Field
            error={errors.url}
            help="Streamable-HTTP MCP endpoint."
            label="URL"
            required
          >
            <Input
              className="font-mono"
              onChange={(e) => set({ url: e.target.value })}
              placeholder="https://mcp.example.com/v1/stream"
              value={s.url}
            />
          </Field>
          <Field label="Description">
            <Textarea
              onChange={(e) => set({ description: e.target.value })}
              placeholder="One sentence — what this server is for."
              value={s.description}
            />
          </Field>
          <Field label="Enabled">
            <label className="flex items-center gap-3">
              <Switch
                checked={s.enabled}
                onCheckedChange={(v) => set({ enabled: v })}
              />
              <span className="text-secondary text-sm">
                {s.enabled
                  ? 'Active — the assistant can use this server.'
                  : 'Disabled — tools hidden from the assistant.'}
              </span>
            </label>
          </Field>
        </CardContent>
      </Card>

      {/* Connection */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Connection</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Field
            help={
              <>
                Tools surface to the assistant as{' '}
                <code className="bg-secondary rounded px-1 py-0.5 font-mono">
                  mcp_{prefix}_{'{tool}'}
                </code>
                . Falls back to the slug when blank.
              </>
            }
            label="Tool prefix"
          >
            <Input
              className="font-mono"
              onChange={(e) => set({ toolPrefix: e.target.value })}
              placeholder={s.slug || 'gh'}
              value={s.toolPrefix}
            />
          </Field>
          <Field label="Timeout">
            <div className="flex items-center gap-3">
              <Input
                className="w-28 font-mono"
                max={300}
                min={1}
                onChange={(e) =>
                  set({ timeout: Number.parseInt(e.target.value, 10) || 0 })
                }
                type="number"
                value={s.timeout}
              />
              <span className="text-secondary text-sm">seconds</span>
            </div>
          </Field>
          <Field label="Verify SSL">
            <label className="flex items-center gap-3">
              <Switch
                checked={s.verifySsl}
                onCheckedChange={(v) => set({ verifySsl: v })}
              />
              <span className="text-secondary text-sm">
                {s.verifySsl ? (
                  'Strict — reject invalid certificates.'
                ) : (
                  <span className="text-warning">
                    Insecure — for in-cluster traffic only.
                  </span>
                )}
              </span>
            </label>
          </Field>
        </CardContent>
      </Card>

      {/* Authentication */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Authentication</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Field label="Auth type">
            <SegmentedControl
              ariaLabel="Auth type"
              onValueChange={(v) => set({ authType: v as MCPServerAuthType })}
              value={s.authType}
            >
              <SegmentedControlItem value="none">
                <Unlock className="size-3.5" />
                None
              </SegmentedControlItem>
              <SegmentedControlItem value="static">
                <KeyRound className="size-3.5" />
                Static header
              </SegmentedControlItem>
              <SegmentedControlItem value="oauth_client_credentials">
                <ShieldCheck className="size-3.5" />
                OAuth client
              </SegmentedControlItem>
            </SegmentedControl>
          </Field>

          {s.authType === 'none' && (
            <p className="bg-secondary text-secondary flex items-center gap-2 rounded-md px-3 py-2 text-sm">
              <Plug className="size-3.5" />
              No credentials sent. Only safe for in-cluster endpoints behind a
              private network.
            </p>
          )}

          {s.authType === 'static' && (
            <>
              <Field
                error={errors.staticHeader}
                help="Sent on every request. Common values: Authorization, X-Api-Key."
                label="Header name"
                required
              >
                <Input
                  className="font-mono"
                  onChange={(e) => set({ staticHeader: e.target.value })}
                  placeholder="Authorization"
                  value={s.staticHeader}
                />
              </Field>
              <Field
                error={errors.staticValue}
                help="Encrypted and write-only — never returned by the API."
                label="Header value"
                required={!server?.has_static_value}
              >
                <SecretField
                  cleared={s.staticCleared}
                  editing={s.staticEditing}
                  onCancel={() =>
                    set({ staticEditing: false, staticValue: '' })
                  }
                  onChange={(v) => set({ staticValue: v })}
                  onClear={() =>
                    set({
                      staticCleared: true,
                      staticEditing: false,
                      staticValue: '',
                    })
                  }
                  onStart={() =>
                    set({
                      staticCleared: false,
                      staticEditing: true,
                      staticValue: '',
                    })
                  }
                  placeholder="Bearer ghp_…"
                  present={!!server?.has_static_value}
                  value={s.staticValue}
                />
              </Field>
            </>
          )}

          {s.authType === 'oauth_client_credentials' && (
            <>
              <Field error={errors.oauthTokenUrl} label="Token URL" required>
                <Input
                  className="font-mono"
                  onChange={(e) => set({ oauthTokenUrl: e.target.value })}
                  placeholder="https://example.com/oauth/token"
                  value={s.oauthTokenUrl}
                />
              </Field>
              <Field error={errors.oauthClientId} label="Client ID" required>
                <Input
                  className="font-mono"
                  onChange={(e) => set({ oauthClientId: e.target.value })}
                  placeholder="Iv1.f9e4…"
                  value={s.oauthClientId}
                />
              </Field>
              <Field
                error={errors.oauthValue}
                help="Encrypted and write-only — never returned by the API."
                label="Client secret"
                required={!server?.has_oauth_client_secret}
              >
                <SecretField
                  cleared={s.oauthCleared}
                  editing={s.oauthEditing}
                  onCancel={() => set({ oauthEditing: false, oauthValue: '' })}
                  onChange={(v) => set({ oauthValue: v })}
                  onClear={() =>
                    set({
                      oauthCleared: true,
                      oauthEditing: false,
                      oauthValue: '',
                    })
                  }
                  onStart={() =>
                    set({
                      oauthCleared: false,
                      oauthEditing: true,
                      oauthValue: '',
                    })
                  }
                  present={!!server?.has_oauth_client_secret}
                  value={s.oauthValue}
                />
              </Field>
              <Field help="Optional. Space-separated." label="Scope">
                <Input
                  className="font-mono"
                  onChange={(e) => set({ oauthScope: e.target.value })}
                  placeholder="repo:read actions:read"
                  value={s.oauthScope}
                />
              </Field>
            </>
          )}
        </CardContent>
      </Card>

      {/* Connection test */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Connection test</CardTitle>
        </CardHeader>
        <CardContent>
          <ConnectionTestPanel
            onResult={(result) => {
              if (result.ok) setDiscoveredTools(result.tools)
            }}
            onTest={runTest}
            server={server}
          />
        </CardContent>
      </Card>

      {/* Ignored tools */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Ignored tools</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-secondary text-sm">
            Tool names listed here are never exposed to the assistant, even when
            the server advertises them.
          </p>
          <IgnoredToolsEditor
            availableTools={discoveredTools}
            onChange={(v) => set({ ignoredTools: v })}
            value={s.ignoredTools}
          />
        </CardContent>
      </Card>
    </div>
  )
}

// Fields shared by the create payload and (minus secrets) the update payload.
// fallow-ignore-next-line complexity
function baseFields(s: FormState) {
  return {
    auth_type: s.authType,
    description: s.description.trim() || null,
    enabled: s.enabled,
    icon: s.icon.trim() || null,
    ignored_tools: s.ignoredTools,
    oauth_client_id:
      s.authType === 'oauth_client_credentials'
        ? s.oauthClientId.trim() || null
        : null,
    oauth_scope:
      s.authType === 'oauth_client_credentials'
        ? s.oauthScope.trim() || null
        : null,
    oauth_token_url:
      s.authType === 'oauth_client_credentials'
        ? s.oauthTokenUrl.trim() || null
        : null,
    static_header:
      s.authType === 'static' ? s.staticHeader.trim() || null : null,
    timeout: s.timeout,
    tool_prefix: s.toolPrefix.trim() || null,
    url: s.url.trim(),
    verify_ssl: s.verifySsl,
  }
}

function buildCreate(s: FormState): MCPServerCreate {
  const data: MCPServerCreate = {
    ...baseFields(s),
    name: s.name.trim(),
    slug: s.slug.trim(),
  }
  if (s.authType === 'static' && s.staticValue) {
    data.static_value = s.staticValue
  }
  if (s.authType === 'oauth_client_credentials' && s.oauthValue) {
    data.oauth_client_secret = s.oauthValue
  }
  return data
}

// Secret rules: a freshly typed value is sent; an explicit clear sends null;
// an untouched secret is omitted so the stored ciphertext survives.
function buildUpdate(s: FormState): MCPServerUpdate {
  const data: MCPServerUpdate = {
    ...baseFields(s),
    name: s.name.trim(),
    slug: s.slug.trim(),
  }
  if (s.staticValue) data.static_value = s.staticValue
  else if (s.staticCleared) data.static_value = null
  if (s.oauthValue) data.oauth_client_secret = s.oauthValue
  else if (s.oauthCleared) data.oauth_client_secret = null
  return data
}

function Field({
  children,
  error,
  help,
  label,
  required,
}: {
  children: React.ReactNode
  error?: string
  help?: React.ReactNode
  label: string
  required?: boolean
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-secondary text-sm">
        {label}
        {required && <RequiredAsterisk />}
      </Label>
      {children}
      {error && (
        <p className="text-danger flex items-center gap-1.5 text-xs">
          <AlertCircle className="size-3.5 shrink-0" />
          {error}
        </p>
      )}
      {help && <p className="text-tertiary text-xs">{help}</p>}
    </div>
  )
}

function hasOauthSecret(s: FormState, server: MCPServer | null): boolean {
  return (
    !!s.oauthValue || (!!server?.has_oauth_client_secret && !s.oauthCleared)
  )
}

function hasStaticSecret(s: FormState, server: MCPServer | null): boolean {
  return !!s.staticValue || (!!server?.has_static_value && !s.staticCleared)
}

// fallow-ignore-next-line complexity
function initialState(server: MCPServer | null): FormState {
  return {
    authType: server?.auth_type ?? 'none',
    description: server?.description ?? '',
    enabled: server?.enabled ?? true,
    icon: server?.icon ?? '',
    ignoredTools: server?.ignored_tools ?? [],
    name: server?.name ?? '',
    oauthCleared: false,
    oauthClientId: server?.oauth_client_id ?? '',
    oauthEditing: false,
    oauthScope: server?.oauth_scope ?? '',
    oauthTokenUrl: server?.oauth_token_url ?? '',
    oauthValue: '',
    slug: server?.slug ?? '',
    slugTouched: !!server,
    staticCleared: false,
    staticEditing: false,
    staticHeader: server?.static_header ?? 'Authorization',
    staticValue: '',
    timeout: server?.timeout ?? 30,
    toolPrefix: server?.tool_prefix ?? '',
    url: server?.url ?? '',
    verifySsl: server?.verify_ssl ?? true,
  }
}

// fallow-ignore-next-line complexity
function validate(
  s: FormState,
  server: MCPServer | null,
): Record<string, string> {
  const errors: Record<string, string> = {}
  if (!s.name.trim()) errors.name = 'Display name is required.'
  if (!s.slug.trim()) errors.slug = 'Slug is required.'
  if (!s.url.trim()) errors.url = 'URL is required.'
  if (s.authType === 'static') {
    if (!s.staticHeader.trim()) errors.staticHeader = 'Header name is required.'
    if (!hasStaticSecret(s, server)) {
      errors.staticValue = 'Header value is required.'
    }
  }
  if (s.authType === 'oauth_client_credentials') {
    if (!s.oauthTokenUrl.trim()) errors.oauthTokenUrl = 'Token URL is required.'
    if (!s.oauthClientId.trim()) errors.oauthClientId = 'Client ID is required.'
    if (!hasOauthSecret(s, server)) {
      errors.oauthValue = 'Client secret is required.'
    }
  }
  return errors
}
