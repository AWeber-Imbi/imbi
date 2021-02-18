import PropTypes from 'prop-types'

export const SelectOptions = PropTypes.arrayOf(
  PropTypes.exact({
    label: PropTypes.string.isRequired,
    value: PropTypes.oneOfType([
      PropTypes.bool,
      PropTypes.string,
      PropTypes.number
    ])
  })
)
