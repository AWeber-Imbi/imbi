import { toTitleCase } from '@/components/admin/blueprints/blueprint-schema-utils'
import type { components } from '@/types/api-generated'

export type IdentitySourceType = Schemas['IdentitySourceType']
export type SecretAuditEvent = Schemas['SecretAuditEvent']
export type SecretBinding = Schemas['SecretBinding']
export type SecretBindingCreate = Schemas['SecretBindingCreate']
export type SecretBindingPatch = Schemas['SecretBindingPatch']
export type SecretBindingValidation = Schemas['SecretBindingValidation']
export type SecretGrant = Schemas['SecretGrant']
export type SecretGrantCreate = Schemas['SecretGrantCreate']
export type SecretGrantPatch = Schemas['SecretGrantPatch']
export type SecretProvider = Schemas['SecretProvider']
export type SecretProviderCreate = Schemas['SecretProviderCreate']
export type SecretProviderPatch = Schemas['SecretProviderPatch']
export type SecretProviderTest = Schemas['SecretProviderTest']
export type SecretProviderType = Schemas['SecretProviderType']
export type SecretResolution = Schemas['SecretResolution']
export type TokenExchangerType = Schemas['TokenExchangerType']
export type WorkloadIdentity = Schemas['WorkloadIdentity']
export type WorkloadIdentityPut = Schemas['WorkloadIdentityPut']

export const DELIVERY_MODES = [
  'file_descriptor',
  'stdin',
  'file',
  'environment',
] as const

export const CREDENTIAL_CLASSES = ['static', 'rotated', 'dynamic'] as const

/**
 * The runner's own setup purposes (SETUP_PURPOSES in the broker). Other
 * purposes are slugs that agents choose, so a grant can also name them.
 */
export const SETUP_PURPOSES = [
  'marketplace_fetch',
  'mcp_server',
  'model_inference',
  'workspace_checkout',
] as const

/** The purpose slug format that the broker accepts. */
export const PURPOSE_PATTERN = /^[a-z][a-z0-9_]{0,63}$/

/** Select options for slugs, labelled in title case. */
export const titleOptions = (values: readonly string[]) =>
  values.map((value) => ({ label: toTitleCase(value), value }))

/** A list of slugs in title case, for a table cell. */
export const titleList = (values: readonly string[]) =>
  values.map(toTitleCase).join(', ')

type Schemas = components['schemas']
