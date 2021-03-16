import React, { useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ContentArea, Error, Loading, Stats } from '../components/'
import { httpGet } from '../utils'
import { Context } from '../state'

export function Dashboard() {
  const [data, setData] = useState(null)
  const [errorMessage, setErrorMessage] = useState(null)
  const [state] = useContext(Context)
  const { t } = useTranslation()

  useEffect(() => {
    if (data === null) {
      const url = new URL(state.baseURL)
      url.pathname = `/dashboard`
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
              url={`/ui/projects?project_type=${row.project_type_id}`}
              value={row.count}
            />
          )
        })}
      </Stats.Container>
    </ContentArea>
  )
}
