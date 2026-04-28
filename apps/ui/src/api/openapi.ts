import { useQuery } from '@tanstack/react-query'

import { apiClient } from './client'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type OpenApiSpec = Record<string, any>

export const fetchOpenApiSpec = (signal?: AbortSignal) =>
  apiClient.get<OpenApiSpec>('/openapi.json', undefined, signal)

export function getSchemaEnum(
  spec: OpenApiSpec,
  schemaName: string,
  propertyName: string,
): string[] {
  const schemas = spec?.components?.schemas || {}
  // Try exact name first, then common OpenAPI suffixed variants
  const candidates = [schemaName, `${schemaName}-Output`, `${schemaName}-Input`]
  for (const name of candidates) {
    const enumValues = schemas[name]?.properties?.[propertyName]?.enum
    if (Array.isArray(enumValues)) return enumValues
  }
  return []
}

export function getSchemaProperties(
  spec: OpenApiSpec,
  schemaName: string,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
): Record<string, any> {
  return spec?.components?.schemas?.[schemaName]?.properties || {}
}

export function useOpenApiSpec() {
  return useQuery({
    queryFn: ({ signal }) => fetchOpenApiSpec(signal),
    queryKey: ['openapi-spec'],
    staleTime: Infinity,
  })
}
