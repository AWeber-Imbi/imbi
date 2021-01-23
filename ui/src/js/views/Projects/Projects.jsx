import PropTypes from 'prop-types'
import React, { useContext, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Alert, ContentArea, Table } from '../../components'
import { FetchContext } from '../../contexts'
import { User } from '../../schema'

function Projects() {
  const { t } = useTranslation()

  const fetchMethod = useContext(FetchContext)
  const [errorMessage, setErrorMessage] = useState(null)
  const [successMessage, setSuccessMessage] = useState(null)
  const [timerHandle, setTimerHandle] = useState(null)

  const columns = [
    {
      title: t('common.name'),
      name: 'name',
      type: 'text',
      tableOptions: {
        className: 'min-w-sm'
      }
    }
  ]

  const data = []

  return (
    <ContentArea
      buttonTitle={t('projects.newProject')}
      pageIcon="fas folder"
      pageTitle={t('projects.title')}>
      {errorMessage !== null && <Alert level="error">{errorMessage}</Alert>}
      {successMessage !== null && (
        <Alert level="success">{successMessage}</Alert>
      )}
      <Table columns={columns} data={data} />
    </ContentArea>
  )
}

Projects.propTypes = {
  user: PropTypes.exact(User)
}

export { Projects }
