import PropTypes from 'prop-types'
import React, { Fragment } from 'react'
import { useTranslation } from 'react-i18next'

import { Icon, Tooltip } from '../../components'

function Facts({ project }) {
  const { t } = useTranslation()
  let lastUpdated = 0
  return (
    <Fragment>
      <div className="border-t border-b border-gray-200 ml-3">
        <dl>
          {project.facts.map((fact, offset) => {
            const updated = Date.parse(fact.recorded_at)
            if (updated > lastUpdated) lastUpdated = updated
            let color = 'border-gray-300'
            if (fact.score >= 0) color = 'border-red-600'
            if (fact.score > 69) color = 'border-yellow-600'
            if (fact.score > 89) color = 'border-green-600'
            return (
              <div
                key={`fact-${fact.fact_type_id}`}
                className={`${
                  offset % 2 === 0 ? 'bg-gray-50' : 'bg-white'
                } px-4 py-2 sm:grid sm:grid-cols-2 sm:gap-4 sm:px-6 border-l-4 ${color}`}>
                <dt className="text-sm font-medium text-gray-500">
                  {fact.name}
                </dt>
                <dd className={`mt-1 text-sm text-gray-900 sm:mt-0`}>
                  <Tooltip value={`${t('terms.score')}: ${fact.score}`}>
                    {fact.data_type === 'boolean' && (
                      <Icon
                        className={
                          fact.value === 'true'
                            ? 'text-green-600'
                            : 'text-red-600'
                        }
                        icon={`fas ${
                          fact.value === 'true' ? 'check' : 'exclamation'
                        }`}
                      />
                    )}
                    {fact.data_type === 'string' &&
                      fact.fact_type === 'enum' &&
                      fact.icon_class !== null && (
                        <Icon className="mr-2" icon={fact.icon_class} />
                      )}
                    {fact.data_type !== 'boolean' &&
                      fact.value !== null &&
                      fact.value}
                    {fact.value !== null &&
                    fact.ui_options.includes('display-as-percentage')
                      ? '%'
                      : ''}
                    {fact.value === null && fact.data_type !== 'boolean' && (
                      <span className="italic text-red-800 text-xs font-light">
                        Not Set
                      </span>
                    )}
                  </Tooltip>
                </dd>
              </div>
            )
          })}
        </dl>
      </div>
      {lastUpdated > 0 && (
        <div className="text-xs italic text-right mt-2">
          Last Updated: {new Intl.DateTimeFormat('en-US').format(lastUpdated)}
        </div>
      )}
    </Fragment>
  )
}
Facts.propTypes = {
  project: PropTypes.object.isRequired
}
export { Facts }
