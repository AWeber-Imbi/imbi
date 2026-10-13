import type { components } from '@/types/api-generated'

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

export const DELIVERY_MODES = [
  'file_descriptor',
  'stdin',
  'file',
  'environment',
] as const

export const CREDENTIAL_CLASSES = ['static', 'rotated', 'dynamic'] as const

type Schemas = components['schemas']
