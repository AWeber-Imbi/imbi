import React from 'react'

import { ContentArea } from '../'

import { Alert } from './Alert'

class AlertPreview extends React.PureComponent {
  render() {
    return (
      <ContentArea
        pageTitle="Alerts"
        pageIcon="fas camera"
        className="space-y-5 w-full">
        <Alert level="error">This is an ERROR level alert</Alert>
        <Alert level="info">This is an INFO level alert</Alert>
        <Alert level="success">This is an SUCCESS level alert</Alert>
        <Alert level="warning">This is an WARNING level alert</Alert>
      </ContentArea>
    )
  }
}
export { AlertPreview }
