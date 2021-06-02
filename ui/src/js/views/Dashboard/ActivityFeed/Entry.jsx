import { DateTime } from 'luxon'
import Gravatar from 'react-gravatar'
import { Link } from 'react-router-dom'
import PropTypes from 'prop-types'
import React from 'react'
import { Trans, useTranslation } from 'react-i18next'

function Entry({ entry }) {
  const { t, i18n } = useTranslation()
  let action = t('dashboard.activityFeed.created')
  if (entry.what === 'updated') action = t('dashboard.activityFeed.updated')
  if (entry.what === 'updated facts')
    action = t('dashboard.activityFeed.updatedFacts')
  const when = DateTime.fromISO(entry.when)
  const namespace = entry.namespace
  const project = entry.project_name
  const displayName = entry.display_name
  return (
    <li className="flex p-2 space-x-3 border-b border-gray-200">
      <Gravatar
        className="h-8 w-8 rounded-full"
        default="mp"
        email={entry.email_address}
        size={22}
      />
      <div className="min-w-0 flex-1">
        <div className="text-sm text-gray-700">
          <Trans i18nKey={'dashboard.activityFeed.entry'} i18n={i18n} t={t}>
            <span className="font-medium text-gray-700">{{ displayName }}</span>{' '}
            <span>{{ action }}</span> the{' '}
            <Link
              to={`/ui/projects/${entry.project_id}`}
              className="font-medium text-blue-700 hover:text-blue-800">
              {{ project }}
            </Link>{' '}
            project in the{' '}
            <Link
              to={`/ui/projects?namespace_id=${entry.namespace_id}`}
              className="font-medium text-blue-700 hover:text-blue-800">
              {{ namespace }}
            </Link>{' '}
            namespace.
          </Trans>
          <p
            className="mt-0.5 text-sm text-gray-500"
            title={when.toLocaleString(DateTime.DATETIME_MED)}>
            {when.toRelative()}
          </p>
        </div>
      </div>
    </li>
  )
}
Entry.propTypes = {
  entry: PropTypes.shape({
    display_name: PropTypes.string,
    email_address: PropTypes.string,
    namespace: PropTypes.string,
    namespace_id: PropTypes.number,
    project_id: PropTypes.number,
    project_name: PropTypes.string,
    project_type: PropTypes.string,
    what: PropTypes.string,
    when: PropTypes.string,
    who: PropTypes.string
  })
}
export { Entry }
