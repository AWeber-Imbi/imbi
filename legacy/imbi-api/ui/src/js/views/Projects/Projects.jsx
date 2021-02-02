import PropTypes from 'prop-types'
import React, { useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Alert, ContentArea, Loading, Table } from '../../components'
import { FetchContext } from '../../contexts'
import { httpGet } from '../../utils'
import { User } from '../../schema'

function Projects() {
  const { t } = useTranslation()

  const [errorMessage, setErrorMessage] = useState(null)
  const fetchMethod = useContext(FetchContext)
  const [initialized, setInitialized] = useState(false)
  const [rows, setRows] = useState([])

  const columns = [
    {
      title: t('terms.namespace'),
      name: 'namespace_slug',
      type: 'text',
      tableOptions: {
        className: 'w-1/12'
      }
    },
    {
      title: t('terms.projectType'),
      name: 'project_type',
      type: 'text',
      tableOptions: {
        className: 'min-w-sm'
      }
    },
    {
      title: t('terms.name'),
      name: 'name',
      type: 'text',
      tableOptions: {
        className: 'min-w-sm'
      }
    }
  ]

  useEffect(() => {
    if (initialized === false) {
      httpGet(
        fetchMethod,
        '/projects',
        (result) => {
          setRows(result)
          setInitialized(true)
        },
        (error) => {
          setErrorMessage(error)
        }
      )
    }
  }, [initialized])

  if (initialized === false) return <Loading />
  return (
    <ContentArea
      buttonDestination="/ui/projects/new"
      buttonTitle={t('projects.newProject')}
      pageIcon="fas folder"
      pageTitle={t('projects.title')}>
      {errorMessage !== null && <Alert level="error">{errorMessage}</Alert>}
      <Table columns={columns} data={rows} />
    </ContentArea>
  )
}

Projects.propTypes = {
  user: PropTypes.exact(User)
}

export { Projects }
