import React from 'react'

import { Documentation } from '../'

import { Alert } from './Alert'

function AlertPreview() {
  return (
    <Documentation
      title="Alerts"
      urlPath="/ui/components/alerts"
      code={`\
<Alert level="info">This is an INFO level alert</Alert>
<Alert level="success">This is an SUCCESS level alert</Alert>
<Alert level="warning">This is an WARNING level alert</Alert>
<Alert level="error">This is an ERROR level alert</Alert>`}
      preview={
        <div className="space-y-2">
          <Alert level="info">This is an INFO level alert</Alert>
          <Alert level="success">This is an SUCCESS level alert</Alert>
          <Alert level="warning">This is an WARNING level alert</Alert>
          <Alert level="error">This is an ERROR level alert</Alert>
        </div>
      }
      properties={`\
- \`level\` - The alert level. One of \`info\`, \`success\`, \`warning\`, or \`error\`.
- \`children\` - The content that goes inside the alert.
`}
    />
  )
}
export { AlertPreview }
