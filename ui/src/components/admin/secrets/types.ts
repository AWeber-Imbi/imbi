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
  'model_inference',
  'workspace_checkout',
] as const

/** The purpose slug format that the broker accepts. */
export const PURPOSE_PATTERN = /^[a-z][a-z0-9_]{0,63}$/

/** A list of slugs in title case, for a table cell. */
export const titleList = (values: readonly string[]) =>
  values.map(toTitleCase).join(', ')

/** Seconds as the largest whole unit, for example 900 as 15 min. */
export const duration = (seconds: number) =>
  seconds % 3600 === 0
    ? `${seconds / 3600} h`
    : seconds % 60 === 0
      ? `${seconds / 60} min`
      : `${seconds} s`

/**
 * JSON with sorted object keys, and without empty-list properties, so that
 * key order and an absent list do not count as a change.
 */
/** The fields of `body` that differ from `original`, by `canonical`. */
export const changedFields = (
  body: Record<string, unknown>,
  original: object,
) =>
  Object.fromEntries(
    Object.entries(body).filter(
      ([key, value]) =>
        canonical(value) !==
        canonical((original as Record<string, unknown>)[key] ?? null),
    ),
  )

export const canonical = (value: unknown): string =>
  JSON.stringify(value, (_key, val: unknown) =>
    val && typeof val === 'object' && !Array.isArray(val)
      ? Object.fromEntries(
          Object.entries(val)
            .filter(([, v]) => !(Array.isArray(v) && !v.length))
            .sort(([a], [b]) => a.localeCompare(b)),
        )
      : val,
  )

/** The audit event types of each Audit filter category. */
export const AUDIT_CATEGORIES = {
  Configuration: [
    'secret_provider_created',
    'secret_provider_updated',
    'secret_provider_deleted',
    'secret_provider_tested',
    'secret_binding_created',
    'secret_binding_updated',
    'secret_binding_deleted',
    'secret_grant_created',
    'secret_grant_updated',
    'secret_grant_deleted',
  ],
  Identity: ['workload_identity_updated', 'workload_identity_deleted'],
  Leases: [
    'secret_lease_renewed',
    'secret_lease_revoked',
    'secret_lease_revocation_failed',
  ],
  Resolutions: [
    'secret_resolution_allowed',
    'secret_resolution_denied',
    'secret_resolution_released',
    'secret_resolution_expired',
    'secret_materialized',
  ],
} as const

type Schemas = components['schemas']
