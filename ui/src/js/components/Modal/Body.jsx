import PropTypes from 'prop-types'
import React from 'react'

class Body extends React.PureComponent {
  render() {
    return (
      <div className={`${this.props.className}`}>{this.props.children}</div>
    )
  }
}
Body.propTypes = {
  children: PropTypes.oneOfType([
    PropTypes.array,
    PropTypes.string,
    PropTypes.element
  ]).isRequired,
  className: PropTypes.string
}
export { Body }
