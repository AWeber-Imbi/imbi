import PropTypes from 'prop-types'
import React, { useContext, useEffect, useState } from 'react'
import { useHistory, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { Alert, Badge, ContentArea, Paginator, Table } from '../../components'
import { FetchContext } from '../../contexts'
import { asOptions, MetadataContext } from '../../metadata'
import { httpGet, setDocumentTitle } from '../../utils'

import { Filter } from './Filter'

function ProjectTable({
  data,
  errorMessage,
  filter,
  offset,
  onRowClick,
  onSortDirection,
  pageSize,
  rowCount,
  setFilter,
  setOffset,
  setPageSize
}) {
  const metadata = useContext(MetadataContext)
  const { t } = useTranslation()
  setDocumentTitle(t('projects.title'))
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
      title: t('terms.healthScore'),
      name: 'project_score',
      type: 'text',
      tableOptions: {
        className: 'text-center',
        headerClassName: 'w-2/12 text-center',
        lookupFunction: (value) => {
          value = parseInt(value)
          let color = 'red'
          if (value === 0) color = 'gray'
          if (value > 69) color = 'yellow'
          if (value > 89) color = 'green'
          return (
            <Badge className="text-sm" color={color}>
              {value.toString()}
            </Badge>
          )
        }
      }
    }
  ]

  console.log('Rendering ProjectTable')
  return (
    <ContentArea
      buttonDestination="/ui/projects/create"
      buttonTitle={t('projects.newProject')}
      pageIcon="fas folder"
      pageTitle={t('projects.title')}>
      {errorMessage !== null && <Alert level="error">{errorMessage}</Alert>}
      <Paginator.Container
        currentPage={offset + 1}
        itemCount={rowCount}
        itemsPerPage={pageSize}
        setCurrentPage={(currentPage) => setOffset(currentPage - 1)}
        setPageSize={setPageSize}>
        <Paginator.Controls
          leftPanel={
            <Filter
              namespaces={asOptions(metadata.namespaces)}
              projectTypes={asOptions(metadata.projectTypes)}
              setFilterValues={setFilter}
              values={filter}
            />
          }
          positionNounSingular="projects.project"
          positionNounPlural="projects.projects"
        />
        <Table columns={columns} data={data} onRowClick={onRowClick} />
        <Paginator.Controls
          showPageSizeSelector={true}
          showStateDisplay={true}
        />
      </Paginator.Container>
    </ContentArea>
  )
}
ProjectTable.propTypes = {
  data: PropTypes.arrayOf(PropTypes.object),
  errorMessage: PropTypes.string,
  filter: PropTypes.object,
  offset: PropTypes.number,
  onRowClick: PropTypes.func,
  onSortDirection: PropTypes.func,
  pageSize: PropTypes.number,
  rowCount: PropTypes.number,
  setFilter: PropTypes.func,
  setOffset: PropTypes.func,
  setPageSize: PropTypes.func
}

function Projects() {
  const fetchContext = useContext(FetchContext)
  const query = new URLSearchParams(useLocation().search)
  const history = useHistory()

  const [state, setState] = useState({
    data: [],
    errorMessage: null,
    filter: {
      namespace: query.get('namespace'),
      project_type: query.get('project_type')
    },
    lastRequest: null,
    offset: 0,
    pageSize: 25,
    rowCount: 0,
    sort: { name: 'asc' }
  })

  function buildURL() {
    const url = new URL(fetchContext.baseURL)
    url.pathname = '/projects'
    Object.entries(state.sort).forEach(([key, value]) => {
      url.searchParams.append(`sort_${key}`, value)
    })
    url.searchParams.append('limit', state.pageSize.toString())
    url.searchParams.append('offset', state.offset.toString())
    Object.entries(state.filter).forEach(([key, value]) => {
      if (value !== null) url.searchParams.append(`where_${key}`, value)
    })
    return url.toString()
  }

  useEffect(() => {
    let kwargs = {}
    Object.keys(state.filter).map((key) => {
      if (state.filter[key] !== null) kwargs[key] = state.filter[key]
    })
    history.push('/ui/projects?' + new URLSearchParams(kwargs).toString())
  }, [state.filter])

  useEffect(() => {
    const url = buildURL()
    if (state.lastRequest === null || state.lastRequest.toString() !== url) {
      httpGet(
        fetchContext.function,
        url,
        (result) => {
          setState({
            ...state,
            data: result.data,
            lastRequest: url,
            rowCount: result.rows
          })
        },
        (error) => {
          setState({ ...state, errorMessage: error })
        }
      )
    }
  }, [state])

  function onSortDirection(column, direction) {
    setState({ ...state, sort: { ...state.sort, [column]: direction } })
  }

  return (
    <ProjectTable
      data={state.data}
      errorMessage={state.errorMessage}
      filter={state.filter}
      offset={state.offset}
      onRowClick={(data) => {
        history.push(`/ui/projects/${data.id}`)
      }}
      onSortDirection={onSortDirection}
      pageSize={state.pageSize}
      rowCount={state.rowCount}
      setFilter={(filter) => setState({ ...state, filter: filter })}
      setOffset={(offset) => setState({ ...state, offset: offset })}
      setPageSize={(pageSize) =>
        setState({ ...state, offset: 0, pageSize: pageSize })
      }
    />
  )
}
export { Projects }
