import PropTypes from 'prop-types'

export const Team = {
  name: PropTypes.string.isRequired,
  slug: PropTypes.string.isRequired,
  icon_class: PropTypes.string,
  group: PropTypes.string
}
