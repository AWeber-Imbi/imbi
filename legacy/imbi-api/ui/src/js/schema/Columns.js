import PropTypes from 'prop-types'

export const Column = {
  castTo: PropTypes.oneOf(['array', 'number']),
  default: PropTypes.oneOfType([
    PropTypes.array,
    PropTypes.bool,
    PropTypes.number,
    PropTypes.string,
    PropTypes.func
  ]),
  description: PropTypes.string,
  format: PropTypes.string,
  maximum: PropTypes.number,
  minimum: PropTypes.number,
  multiple: PropTypes.bool,
  name: PropTypes.string.isRequired,
  omitOnAdd: PropTypes.bool,
  options: PropTypes.arrayOf(
    PropTypes.exact({
      label: PropTypes.string.isRequired,
      value: PropTypes.oneOfType([
        PropTypes.bool,
        PropTypes.number,
        PropTypes.string
      ])
    })
  ),
  placeholder: PropTypes.oneOfType([PropTypes.string, PropTypes.element]),
  readOnly: PropTypes.bool,
  sortCallback: PropTypes.func,
  sortDirection: PropTypes.oneOf([null, 'asc', 'desc']),
  tableOptions: PropTypes.exact({
    className: PropTypes.string,
    lookupFunction: PropTypes.func,
    headerClassName: PropTypes.string,
    hide: PropTypes.bool,
    sortable: PropTypes.bool
  }),
  title: PropTypes.string.isRequired,
  type: PropTypes.oneOf([
    'hidden',
    'icon',
    'internal',
    'number',
    'select',
    'text',
    'textarea',
    'toggle'
  ]).isRequired
}

export const Columns = PropTypes.arrayOf(PropTypes.exact(Column))
