import { NavLink } from 'react-router-dom'
import PropTypes from 'prop-types'
import React from 'react'

function Button({ children, className, destination, disabled, onClick, type }) {
  if (destination !== undefined)
    return (
      <NavLink
        className={!disabled ? className : 'btn-disabled'}
        to={destination}>
        {children}
      </NavLink>
    )
  return (
    <button
      className={!disabled ? className : 'btn-disabled'}
      disabled={disabled}
      onClick={(event) => {
        if (onClick !== undefined) {
          event.preventDefault()
          onClick(event)
        }
      }}
      type={type}>
      {children}
    </button>
  )
}

Button.defaultProps = {
  className: 'btn-white',
  disabled: false,
  type: 'button'
}

Button.propTypes = {
  children: PropTypes.oneOfType([
    PropTypes.arrayOf(PropTypes.element),
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
