import PropTypes from 'prop-types'

export const User = {
  authenticated: PropTypes.bool,
  created_at: PropTypes.string,
  username: PropTypes.string,
  display_name: PropTypes.string,
  email_address: PropTypes.string,
  user_type: PropTypes.oneOf(['internal', 'ldap']),
  external_id: PropTypes.string,
  groups: PropTypes.arrayOf(PropTypes.string),
  permissions: PropTypes.arrayOf(PropTypes.string),
  last_refreshed_at: PropTypes.string,
  last_seen_at: PropTypes.string,
  integrations: PropTypes.arrayOf(PropTypes.string)
}
