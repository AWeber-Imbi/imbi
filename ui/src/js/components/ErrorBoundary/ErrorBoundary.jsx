import PropTypes from 'prop-types'
import React from 'react'
import * as Sentry from '@sentry/react'

import { Error } from '../'

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  componentDidCatch(error, errorInfo) {
    Sentry.configureScope((scope) => {
      Object.keys(errorInfo).forEach((key) => {
        scope.setExtra(key, errorInfo[key])
      })
    })
    Sentry.captureException(error)
  }

  static getDerivedStateFromError(error) {
    return { error: 'Internal Application Error', value: error }
  }

  render() {
    if (this.state.error !== null) return <Error>{this.state.error}</Error>
    return this.props.children
  }
}
ErrorBoundary.propTypes = {
  children: PropTypes.oneOfType([
    PropTypes.element,
    PropTypes.node,
    PropTypes.arrayOf(PropTypes.element),
    PropTypes.arrayOf(PropTypes.node)
  ])
}
export { ErrorBoundary }
