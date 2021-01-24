import PropTypes from 'prop-types'

export const Column = {
  default: PropTypes.oneOfType([PropTypes.string, PropTypes.func]),
  description: PropTypes.string,
  format: PropTypes.string,
  maximum: PropTypes.number,
  minimum: PropTypes.number,
  multiple: PropTypes.bool,
  name: PropTypes.string.isRequired,
  options: PropTypes.arrayOf(
    PropTypes.exact({
      label: PropTypes.string.isRequired,
      value: PropTypes.string.isRequired
    })
  ),
  placeholder: PropTypes.oneOfType([PropTypes.string, PropTypes.element]),
  readOnly: PropTypes.bool,
  tableOptions: PropTypes.exact({
    className: PropTypes.string,
    headerClassName: PropTypes.string,
    hide: PropTypes.bool,
    sortable: PropTypes.bool
  }),
  title: PropTypes.string.isRequired,
  type: PropTypes.oneOf([
    'icon',
    'internal',
    'number',
    'select',
    'text',
    'textarea'
  ]).isRequired
}

export const Columns = PropTypes.arrayOf(PropTypes.exact(Column))
