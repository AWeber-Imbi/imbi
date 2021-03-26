import React, { useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ContentArea, Error, Loading } from '../../components/'
import { Context } from '../../state'
import { httpGet } from '../../utils'
import { Stats } from './Stats/'

export function Dashboard() {
  const [data, setData] = useState(null)
  const [errorMessage, setErrorMessage] = useState(null)
  const [state, dispatch] = useContext(Context)
  const { t } = useTranslation()

  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        url: new URL('/ui/', state.baseURL)
      }
    })
  }, [])

  useEffect(() => {
    if (data === null) {
      const url = new URL('/dashboard', state.baseURL)
      httpGet(
        state.fetch,
        url,
        (result) => {
          setData(result)
        },
        (error) => {
          setErrorMessage(error)
        }
      )
    }
  }, [data])

  if (errorMessage !== null) return <Error>{errorMessage}</Error>
  if (data === null) return <Loading />

  return (
    <div className="flex-grow mt-2 space-y-3">
      <ContentArea
        className="flex-grow"
        pageIcon="fas chart-line"
        pageTitle={t('dashboard.namespaces')}>
        <Stats.Container>
          {data.namespaces.map((row) => {
            if (row.count <= 1) return null
            return (
              <Stats.Value
                key={`stats-${row.name}`}
                title={row.name}
                icon={row.icon}
                url={`/ui/projects?namespace_id=${row.namespace_id}`}
                value={row.count}
              />
            )
          })}
        </Stats.Container>
      </ContentArea>
      <ContentArea
        className="flex-grow"
        pageIcon="fas chart-line"
        pageTitle={t('dashboard.projectTypes')}>
        <Stats.Container>
          {data.project_types.map((row) => {
            return (
              <Stats.Value
                key={`stats-${row.name}`}
                title={row.count === 1 ? row.name : row.plural}
                icon={row.icon}
                url={`/ui/projects?project_type_id=${row.project_type_id}`}
                value={row.count}
              />
            )
          })}
        </Stats.Container>
      </ContentArea>
    </div>
  )
}
