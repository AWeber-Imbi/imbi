import React, { useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Context } from '../../state'
import { httpGet } from '../../utils'
import { Alert, Badge, ContentArea, Loading, Table } from '../../components'

function colorizeValue(value) {
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

function formatNumber(value) {
  return value.toLocaleString()
}

function NamespaceKPIs() {
  const [globalState, dispatch] = useContext(Context)
  const [state, setState] = useState({
    data: [],
    fetched: false,
    errorMessage: null
  })
  const { t } = useTranslation()

  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        title: t('reports.namespaceKPIs.title'),
        url: new URL('/ui/reports/namespace-kpis', globalState.baseURL)
      }
    })
  }, [])

  useEffect(() => {
    if (state.fetched === false) {
      const url = new URL('/reports/namespace-kpis', globalState.baseURL)
      httpGet(
        globalState.fetch,
        url,
        (result) => {
          setState({ data: result, fetched: true, errorMessage: null })
        },
        (error) => {
          setState({ data: [], fetched: true, errorMessage: error })
        }
      )
    }
  }, [state.fetched])

  const columns = [
    {
      title: t('terms.namespace'),
      name: 'namespace',
      type: 'text',
      tableOptions: {
        className: 'truncate',
        headerClassName: 'w-3/12'
      }
    },
    {
      title: t('reports.namespaceKPIs.projects'),
      name: 'projects',
      type: 'text',
      tableOptions: {
        className: 'text-right',
        headerClassName: 'pl-2 text-right',
        lookupFunction: formatNumber
      }
    },
    {
      title: t('reports.namespaceKPIs.stackHealthScore'),
      name: 'stack_health_score',
      type: 'text',
      tableOptions: {
        className: 'text-center',
        headerClassName: 'pl-2 text-center',
        lookupFunction: colorizeValue
      }
    },
    {
      title: t('reports.namespaceKPIs.avgProjectScore'),
      name: 'avg_project_score',
      type: 'text',
      tableOptions: {
        className: 'text-center',
        headerClassName: 'pl-2 text-right',
        lookupFunction: colorizeValue
      }
    },
    {
      title: t('reports.namespaceKPIs.totalProjectScore'),
      name: 'total_project_score',
      type: 'text',
      tableOptions: {
        className: 'text-right',
        headerClassName: 'pl-2 text-right',
        lookupFunction: formatNumber
      }
    },
    {
      title: t('reports.namespaceKPIs.totalPossibleProjectScore'),
      name: 'total_possible_project_score',
      type: 'text',
      tableOptions: {
        className: 'text-right',
        headerClassName: 'pl-2 text-right',
        lookupFunction: formatNumber
      }
    },
    {
      title: t('reports.namespaceKPIs.totalProjectScorePercentage'),
      name: 'percent_of_tpps',
      type: 'text',
      tableOptions: {
        className: 'text-right',
        headerClassName: 'pl-2 text-right'
      }
    }
  ]

  if (state.errorMessage !== null)
    return <Alert level="error">{state.errorMessage}</Alert>
  if (state.fetched === false) return <Loading />
  return (
    <ContentArea
      className="flex-grow"
      pageIcon="fas chart-line"
      pageTitle="Namespace KPIs">
      <Table columns={columns} data={state.data} />
      <div className="italic text-gray-600 text-right text-xs">
        {t('reports.lastUpdated', { lastUpdated: new Date().toString() })}
      </div>
      <div className="ml-4 text-gray-600">
        <h1 className="font-medium my-2">Definitions</h1>
        <dl className="ml-2 text-sm">
          <dt className="font-medium">Stack Health Score</dt>
          <dd>
            The 95th Percentile of scores for all projects in the namespace
          </dd>
          <dt className="font-medium mt-2">Avg Project Score</dt>
          <dd>The average project score for all projects in the namespace</dd>
          <dt className="font-medium mt-2">Total Project Score</dt>
          <dd>
            The sum of the project scores for all projects in the namespace
          </dd>
          <dt className="font-medium mt-2">Total Possible Score</dt>
          <dd>
            The sum of the maximum possible project score for all projects in
            the namespace
          </dd>
          <dt className="font-medium mt-2">TPS %</dt>
          <dd>
            The Total Project Score percentage of the Total Possible Score
          </dd>
        </dl>
      </div>
    </ContentArea>
  )
}
export { NamespaceKPIs }
