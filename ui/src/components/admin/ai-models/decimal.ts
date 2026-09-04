// Pydantic renders `Decimal` as a JSON string, so cost and spend-cap
// fields arrive as strings even though they are written back as numbers.
// Coerce once at the edge so form state and diffs stay numeric.
export function decimalToNumber(
  value: null | number | string | undefined,
): null | number {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isNaN(parsed) ? null : parsed
}
