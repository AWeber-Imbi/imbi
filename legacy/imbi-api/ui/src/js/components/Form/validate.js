import { validate } from 'jsonschema'
import { isURL } from '../../utils'

/**
 * Validates an object using JSON Schema
 * @param values
 * @param jsonSchema
 * @returns [boolean, {[p: string]: string}]
 */
export function validateObject(values, jsonSchema) {
  const errors = {}
  const result = validate(values, jsonSchema)
  if (result.errors.length > 0) {
    result.errors.map((err) => {
      err.path.map((field) => {
        if (values[field] !== null) {
          errors[field] = err.message
        }
      })
    })
  }
  return [Object.keys(errors).length === 0, errors]
}

/**
 * Validates an object containing key value pairs of identifier, URL
 * returning an array of ids that did not pass the validation.
 *
 * @param values
 * @returns [boolean, [string]]
 */
export function validateURLs(values) {
  const errors = Object.entries(values)
    .map(([key, value]) => {
      const invalid = value !== undefined && value !== '' && !isURL(value)
      return invalid ? key : null
    })
    .filter((key) => key !== null)
  return [errors.length === 0, errors]
}
