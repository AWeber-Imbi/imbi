import { apiClient } from './client'
import { useQuery } from '@tanstack/react-query'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type OpenApiSpec = Record<string, any>

export const fetchOpenApiSpec = () =>
  apiClient.get<OpenApiSpec>('/openapi.json')

export function useOpenApiSpec() {
  return useQuery({
    queryKey: ['openapi-spec'],
    queryFn: fetchOpenApiSpec,
    staleTime: Infinity,
  })
}

export function getSchemaEnum(
  spec: OpenApiSpec,
  schemaName: string,
  propertyName: string
): string[] {
  const schemas = spec?.components?.schemas || {}
  // Try exact name first, then common OpenAPI suffixed variants
  const candidates = [
    schemaName,
    `${schemaName}-Output`,
    `${schemaName}-Input`,
  ]
  for (const name of candidates) {
    const enumValues = schemas[name]?.properties?.[propertyName]?.enum
    if (Array.isArray(enumValues)) return enumValues
  }
  return []
}

export function getSchemaProperties(
  spec: OpenApiSpec,
  schemaName: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
): Record<string, any> {
  return spec?.components?.schemas?.[schemaName]?.properties || {}
}
