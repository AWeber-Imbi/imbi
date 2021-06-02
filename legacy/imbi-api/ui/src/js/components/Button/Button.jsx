import { NavLink } from 'react-router-dom'
import PropTypes from 'prop-types'
import React from 'react'

class Button extends React.PureComponent {
  render() {
    if (this.props.destination !== undefined)
      return (
        <NavLink
          className={
            !this.props.disabled ? this.props.className : 'btn-disabled'
          }
          to={this.props.destination}>
          {this.props.children}
        </NavLink>
      )
    return (
      <button
        className={!this.props.disabled ? this.props.className : 'btn-disabled'}
        disabled={this.props.disabled}
        onClick={(event) => {
          if (this.props.onClick !== undefined) {
            event.preventDefault()
            this.props.onClick(event)
          }
        }}
        type={this.props.type}>
        {this.props.children}
      </button>
    )
  }
}
Button.defaultProps = {
  className: 'btn-white',
  disabled: false,
  type: 'button'
}
Button.propTypes = {
  children: PropTypes.oneOfType([
    PropTypes.arrayOf(
      PropTypes.oneOfType([PropTypes.element, PropTypes.string])
    ),
    PropTypes.element,
    PropTypes.string
  ]).isRequired,
  className: PropTypes.string,
  destination: PropTypes.string,
  disabled: PropTypes.bool,
  onClick: PropTypes.func,
  type: PropTypes.string
}
export { Button }
