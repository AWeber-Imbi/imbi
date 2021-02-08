import PropTypes from 'prop-types'
import React, { useContext, useEffect, useState } from 'react'
import { useHistory, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import {
  Alert,
  ContentArea,
  Loading,
  SyncedPaginator,
  Table
} from '../../components'
import { FetchContext } from '../../contexts'
import { httpGet, setDocumentTitle } from '../../utils'
import { User } from '../../schema'

function Projects() {
  const query = useQuery()
  const { t } = useTranslation()

  const [errorMessage, setErrorMessage] = useState(null)
  const fetch = useContext(FetchContext)
  const [filter, setFilter] = useState({
    namespace: query.get('namespace'),
    project_type: query.get('project_type')
  })
  const history = useHistory()
  const [initialized, setInitialized] = useState(false)
  const [lastRequest, setLastRequest] = useState(null)
  const [offset, setOffset] = useState(0)
  const [pageSize, setPageSize] = useState(25)
  const [rowCount, setRowCount] = useState(0)
  const [rows, setRows] = useState([])
  const [sort, setSort] = useState({ name: null })

  function onRowClick(data) {
    history.push(`/ui/projects/${data['id']}`)
  }

  function onSortDirection(column, direction) {
    setSort({ ...sort, [column]: direction })
  }

  function useQuery() {
    return new URLSearchParams(useLocation().search)
  }

  const columns = [
    {
      title: t('terms.namespace'),
      name: 'namespace',
      sortCallback: onSortDirection,
      type: 'text',
      tableOptions: {
        className: 'truncate',
        headerClassName: 'w-3/12'
      }
    },
    {
      title: t('terms.name'),
      name: 'name',
      sortCallback: onSortDirection,
      type: 'text',
      tableOptions: {
        className: 'truncate',
        headerClassName: 'w-3/12'
      }
    },
    {
      title: t('terms.projectType'),
      name: 'project_type',
      sortCallback: onSortDirection,
      type: 'text',
      tableOptions: {
        className: 'truncate',
        headerClassName: 'w-3/12'
      }
    },
    {
      title: t('terms.description'),
      name: 'description',
      type: 'text',
      tableOptions: {
        className: 'truncate',
        headerClassName: 'w-3/12'
      }
    }
  ]

  useEffect(() => {
    const url = new URL(fetch.baseURL)
    url.pathname = '/projects'
    Object.entries(sort).forEach(([key, value]) => {
      url.searchParams.append(`sort_${key}`, value)
    })
    url.searchParams.append('limit', pageSize.toString())
    url.searchParams.append('offset', offset.toString())
    Object.entries(filter).forEach(([key, value]) => {
      if (value !== null) url.searchParams.append(`where_${key}`, value)
    })
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
  }, [lastRequest, offset, pageSize, sort])

  setDocumentTitle(t('projects.title'))

  if (initialized === false) return <Loading />
  return (
    <ContentArea
      buttonDestination="/ui/projects/new"
      buttonTitle={t('projects.newProject')}
      pageIcon="fas folder"
      pageTitle={t('projects.title')}>
      {errorMessage !== null && <Alert level="error">{errorMessage}</Alert>}
      <SyncedPaginator.Container
        itemCount={rowCount}
        itemsPerPage={pageSize}
        offset={offset}
        onChange={setOffset}
        onPageSize={setPageSize}>
        <SyncedPaginator.Paginator
          positionNounSingular="projects.project"
          positionNounPlural="projects.projects"
          showStateDisplay={true}
        />
        <Table columns={columns} data={rows} onRowClick={onRowClick} />
        <SyncedPaginator.Paginator
          showPageSizeSelector={true}
          showStateDisplay={true}
        />
      </SyncedPaginator.Container>
    </ContentArea>
  )
}
Projects.propTypes = {
  user: PropTypes.exact(User)
}
export { Projects }
