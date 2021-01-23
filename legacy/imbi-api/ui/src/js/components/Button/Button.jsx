import PropTypes from 'prop-types'
import React from 'react'

function Button({ children, className, disabled, onClick, type }) {
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
  children: PropTypes.oneOfType([PropTypes.string, PropTypes.element]).isRequired,
  className: PropTypes.string,
  disabled: PropTypes.bool,
  onClick: PropTypes.func,
  type: PropTypes.string
}

export { Button }
