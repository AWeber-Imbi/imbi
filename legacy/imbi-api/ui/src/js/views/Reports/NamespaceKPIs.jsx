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
        headerClassName: 'w-1/12 text-right',
        lookupFunction: formatNumber
      }
    },
    {
      title: t('reports.namespaceKPIs.stackHealthScore'),
      name: 'stack_health_score',
      type: 'text',
      tableOptions: {
        className: 'text-center',
        headerClassName: 'w-2/12 text-center',
        lookupFunction: colorizeValue
      }
    },
    {
      title: t('reports.namespaceKPIs.totalProjectScore'),
      name: 'total_project_score',
      type: 'text',
      tableOptions: {
        className: 'text-right',
        headerClassName: 'w-2/12 text-right',
        lookupFunction: formatNumber
      }
    },
    {
      title: t('reports.namespaceKPIs.totalPossibleProjectScore'),
      name: 'total_possible_project_score',
      type: 'text',
      tableOptions: {
        className: 'text-right',
        headerClassName: 'w-2/12 text-right',
        lookupFunction: formatNumber
      }
    },
    {
      title: t('reports.namespaceKPIs.totalProjectScorePercentage'),
      name: 'percent_of_tpps',
      type: 'text',
      tableOptions: {
        className: 'text-right',
        headerClassName: 'w-2/12 text-right'
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
      <div className="text-right mt-2 text-xs text-gray-600 italic">
        {t('reports.lastUpdated', { lastUpdated: new Date().toString() })}
      </div>
    </ContentArea>
  )
}
export { NamespaceKPIs }
