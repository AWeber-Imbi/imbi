import PropTypes from "prop-types"

export const Column = {
  default: PropTypes.string,
  description: PropTypes.string,
  name: PropTypes.string.isRequired,
  options: PropTypes.arrayOf(PropTypes.exact({
    label: PropTypes.string.isRequired,
    value: PropTypes.string.isRequired
  })),
  placeholder: PropTypes.oneOfType([PropTypes.string, PropTypes.element]),
  tableOptions: PropTypes.exact({
    className: PropTypes.string,
    headerClassName: PropTypes.string,
    hide: PropTypes.bool,
    sortable: PropTypes.bool
  }),
  title: PropTypes.string.isRequired,
  type: PropTypes.oneOf(["icon", "select", "text", "textarea"]).isRequired
}

export const Columns = PropTypes.arrayOf(PropTypes.exact(Column))
