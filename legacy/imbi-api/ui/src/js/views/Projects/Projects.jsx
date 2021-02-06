import PropTypes from 'prop-types'
import React, { useContext, useEffect, useState } from 'react'
import { useHistory } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import {
  Alert,
  ContentArea,
  Loading,
  Pagination,
  Table
} from '../../components'
import { FetchContext } from '../../contexts'
import { httpGet, setDocumentTitle } from '../../utils'
import { User } from '../../schema'

function Projects() {
  const { t } = useTranslation()

  const [errorMessage, setErrorMessage] = useState(null)
  const fetch = useContext(FetchContext)
  const [filter, setFilter] = useState({})
  const [initialized, setInitialized] = useState(false)
  const [lastRequest, setLastRequest] = useState(null)
  const [offset, setOffset] = useState(0)
  const [pageSize, setPageSize] = useState(10)
  const [rowCount, setRowCount] = useState(0)
  const [rows, setRows] = useState([])
  const [sort, setSort] = useState({ name: null })
  const history = useHistory()

  function onRowClick(data) {
    history.push(`/ui/projects/${data['id']}`)
  }

  function onSortDirection(column, direction) {
    setSort({ ...sort, [column]: direction })
  }

  const columns = [
    {
      title: t('terms.namespace'),
      name: 'namespace_slug',
      sortCallback: onSortDirection,
      type: 'text',
      tableOptions: {
        className: 'truncate',
        headerClassName: 'w-1/12'
      }
    },
    {
      title: t('terms.projectType'),
      name: 'project_type',
      sortCallback: onSortDirection,
      type: 'text',
      tableOptions: {
        className: 'truncate',
        headerClassName: 'w-2/12'
      }
    },
    {
      title: t('terms.name'),
      name: 'name',
      sortCallback: onSortDirection,
      type: 'text',
      tableOptions: {
        className: 'truncate',
        headerClassName: 'w-2/12'
      }
    },
    {
      title: t('terms.description'),
      name: 'description',
      type: 'text',
      tableOptions: {
        className: 'truncate',
        headerClassName: 'w-7/12'
      }
    }
  ]

  useEffect(() => {
    const url = new URL(fetch.baseURL)
    url.pathname = '/projects'
    Object.entries(sort).forEach(([key, value]) => {
      url.searchParams.append(`sort_${key}`, value)
    })
    url.searchParams.append('offset', offset.toString())
    if (lastRequest === null || lastRequest.toString() !== url.toString()) {
      setLastRequest(url)
      httpGet(
        fetch.function,
        url,
        (result) => {
          setRowCount(result.rows)
          setRows(result.data)
          setInitialized(true)
        },
        (error) => {
          setErrorMessage(error)
        }
      )
    }
  }, [lastRequest, sort])

  setDocumentTitle(t('projects.title'))

  if (initialized === false) return <Loading />
  return (
    <ContentArea
      buttonDestination="/ui/projects/new"
      buttonTitle={t('projects.newProject')}
      pageIcon="fas folder"
      pageTitle={t('projects.title')}>
      {errorMessage !== null && <Alert level="error">{errorMessage}</Alert>}
      <Table columns={columns} data={rows} onRowClick={onRowClick} />
      <Pagination
        currentPage={offset + 1}
        itemCount={rowCount}
        itemsPerPage={pageSize}
        onChange={(page) => {
          setOffset(page - 1)
          console.log('Offset set to ', page - 1)
        }}
      />
    </ContentArea>
  )
}

Projects.propTypes = {
  user: PropTypes.exact(User)
}

export { Projects }
