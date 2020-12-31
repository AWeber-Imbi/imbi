import PropTypes from 'prop-types'

export const CookieCutter = {
    name: PropTypes.string.isRequired,
    type: PropTypes.oneOf(['dashboard', 'project']).isRequired,
    project_type: PropTypes.string.isRequired,
    description: PropTypes.string,
    git_url: PropTypes.string.isRequired,
}
