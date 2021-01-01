import PropTypes from "prop-types"

export const Column = {
  title: PropTypes.string.isRequired,
  name: PropTypes.string.isRequired,
  type: PropTypes.oneOf(["icon", "select", "text", "textarea"]).isRequired,
  description: PropTypes.string,
  options: PropTypes.arrayOf(PropTypes.exact({
    label: PropTypes.string.isRequired,
    value: PropTypes.string.isRequired
  })),
  placeholder: PropTypes.oneOfType([PropTypes.string, PropTypes.element]),
  default: PropTypes.string,
  tableOptions: PropTypes.exact({
    headerClassName: PropTypes.string,
    sortable: PropTypes.bool
  })
}

export const Columns = PropTypes.arrayOf(PropTypes.exact(Column))
