import PropTypes from 'prop-types'
import React from 'react'
import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { User } from '../../schema'

function Project({ user }) {
  const { t } = useTranslation()
  const { projectId } = useParams()
  return <div>{projectId}</div>
}

Project.propTypes = {
  user: PropTypes.exact(User)
}

export { Project }
