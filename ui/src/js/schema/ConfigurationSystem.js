export const ConfigurationSystem = {
  "$ref": "schema/ConfigurationSystem.js",
  "$schema": "http://json-schema.org/draft-07/schema#",
  type: "object",
  properties: {
    name: {
      type: "string"
    },
    description: {
      oneOf: [
        {type: "string"},
        {type: "null"}
      ]
    },
    icon_class: {
      oneOf: [
        {type: "string"},
        {type: "null"}
      ]
    }
  },
  additionalProperties: false,
  required: [
    "name"
  ]
}
