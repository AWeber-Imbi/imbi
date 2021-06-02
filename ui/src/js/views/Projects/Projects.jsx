import React, { useContext, useEffect, useState } from 'react'
import { Link, useHistory, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { Alert, Icon, Loading } from '../../components'
import { Context } from '../../state'
import { httpGet } from '../../utils'

import { DataTable } from './DataTable'
import { Filter } from './Filter'
import { asOptions } from '../../metadata'

function buildSortDefault(sort) {
  const value = {}
  const sortMatches = sort.match(
    /(?:(name|namespace|project_score|project_type) (asc|desc))/g
  )
  if (sortMatches !== null) {
    sortMatches.map((match) => {
      const [column, direction] = match.split(' ')
      value[column] = direction
    })
  }
  if (Object.keys(value).length === 0) {
    value.namespace = 'asc'
    value.name = 'asc'
  }
  return value
}

function Projects() {
  const [errorMessage, setErrorMessage] = useState(null)
  const [globalState, dispatch] = useContext(Context)
  const history = useHistory()
  const query = new URLSearchParams(useLocation().search)
  const sortOrder = ['namespace', 'project_type', 'name', 'project_score']
  const [state, setState] = useState({
    data: [],
    fetching: false,
    filter: {
      include_archived: query.get('include_archived') === 'true',
      namespace_id: query.get('namespace_id'),
      project_type_id: query.get('project_type_id'),
      project_name: query.get('project_name')
    },
    lastRequest: null,
    offset: parseInt(query.get('offset') || '0'),
    pageSize: parseInt(query.get('limit') || '25'),
    rowCount: 0,
    sort: buildSortDefault(query.get('sort') || '')
  })
  const [successMessage, setSuccessMessage] = useState(query.get('message'))
  const { t } = useTranslation()

  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        url: buildURL('/ui/projects'),
        title: 'projects.title'
      }
    })
  }, [])

  useEffect(() => {
    const url = buildURL()
    if (
      state.fetching === false &&
      (state.lastRequest === null || state.lastRequest.toString() !== url)
    ) {
      setState({ ...state, fetching: true })
      httpGet(
        globalState.fetch,
        url,
        (result) => {
          const stateURL = buildURL('/ui/projects')
          dispatch({
            type: 'SET_CURRENT_PAGE',
            payload: {
              url: stateURL,
              title: 'projects.title'
            }
          })
          history.push(
            `${stateURL.pathname}?${stateURL.searchParams.toString()}`
          )
          setState({
            ...state,
            data: result.data,
            fetching: false,
            lastRequest: url,
            rowCount: result.rows
          })
        },
        (error) => {
          setErrorMessage(t('projects.requestError', { error: error }))
          setState({
            ...state,
            fetching: false,
            filter: {
              include_archived: false,
              namespace_id: null,
              project_type_id: null
            },
            lastRequest: url,
            sort: { name: 'asc' }
          })
        }
      )
    }
  }, [state.filter, state.pageSize, state.offset, state.sort])

  // Remove the error message after 30 seconds
  useEffect(() => {
    if (errorMessage !== null) {
      const timerHandle = setTimeout(() => {
        setErrorMessage(null)
      }, 30000)
      return () => {
        clearTimeout(timerHandle)
      }
    }
  }, [errorMessage])

  // Remove the message after 30 seconds
  useEffect(() => {
    if (successMessage) {
      const timerHandle = setTimeout(() => {
        setSuccessMessage(null)
      }, 30000)
      return () => {
        clearTimeout(timerHandle)
      }
    }
  }, [successMessage])

  function buildURL(path = '/projects') {
    const url = new URL(path, globalState.baseURL)
    Object.entries(state.filter).forEach(([key, value]) => {
      if (value !== null && value.length > 0)
        url.searchParams.append(key, value)
    })
    const sortValues = []
    sortOrder.map((key) => {
      if (['asc', 'desc'].includes(state.sort[key]))
        sortValues.push(`${key} ${state.sort[key]}`)
    })
    if (sortValues.length > 0)
      url.searchParams.append('sort', sortValues.join(','))
    url.searchParams.append('limit', state.pageSize.toString())
    url.searchParams.append('offset', state.offset.toString())
    return url
  }

  function onSortDirection(column, direction) {
    const sort = { ...state.sort }
    if (direction === null) {
      if (sort[column] !== undefined) delete sort[column]
    } else if (state.sort[column] !== direction) {
      sort[column] = direction
    }
    if (state.sort !== sort) {
      setState({ ...state, sort: sort })
    }
  }

  if (state.lastRequest === null) return <Loading />
  return (
    <div className="m-0 px-4 py-3 space-y-3">
      {successMessage !== null && (
        <Alert className="mt-3" level="success">
          {successMessage}
        </Alert>
      )}
      {errorMessage !== null && (
        <Alert className="mt-3" level="error">
          {errorMessage}
        </Alert>
      )}
      <div className="flex items-center space-x-2 md:space-x-10">
        <Filter
          disabled={state.fetching}
          namespaces={asOptions(globalState.metadata.namespaces)}
          projectTypes={asOptions(globalState.metadata.projectTypes)}
          setFilterValues={(values) => {
            setState({ ...state, filter: values })
          }}
          values={state.filter}
        />
        <Link to="/ui/projects/create" className="flex-auto text-right text-sm">
          <button className="btn-green whitespace-nowrap">
            <Icon className="lg:mr-2" icon="fas plus-circle" />
            <span className="hidden lg:inline-block">
              {t('headerNavItems.newProject')}
            </span>
          </button>
        </Link>
      </div>
      <DataTable
        data={state.data}
        disabled={state.fetching}
        errorMessage={errorMessage}
        filter={state.filter}
        offset={state.offset}
        onSortDirection={onSortDirection}
        pageSize={state.pageSize}
        rowCount={state.rowCount}
        rowURL={(data) => `/ui/projects/${data.id}`}
        setOffset={(offset) => {
          if (state.offset !== offset) {
            setState({ ...state, offset: offset })
          }
        }}
        setPageSize={(pageSize) => {
          if (state.pageSize !== pageSize) {
            setState({ ...state, offset: 0, pageSize: pageSize })
          }
        }}
        sort={state.sort}
      />
    </div>
  )
}
export { Projects }
