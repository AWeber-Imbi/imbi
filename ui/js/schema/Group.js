import PropTypes from 'prop-types'

export const Group = {
    name: PropTypes.string.isRequired,
    group_type: PropTypes.oneOf(['internal', 'ldap']).isRequired,
    external_id: PropTypes.string,
    permissions: PropTypes.arrayOf(PropTypes.string),
}
