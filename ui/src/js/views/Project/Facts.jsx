import PropTypes from 'prop-types'
import React from 'react'
import { useTranslation } from 'react-i18next'

import { Button, Card, Icon, Tooltip } from '../../components'

import { EditFacts } from './EditFacts'

function Fact({ fact, offset }) {
  const { t } = useTranslation()
  let color = 'border-gray-300'
  if (fact.score > 0) color = 'border-red-600'
  if (fact.score > 69) color = 'border-yellow-600'
  if (fact.score > 89) color = 'border-green-600'
  if (fact.data_type === 'boolean' && fact.value === 'true')
    color = 'border-green-600'
  if (fact.data_type === 'boolean' && fact.value === 'false')
    color = 'border-red-600'
  return (
    <div
      key={`fact-${fact.fact_type_id}`}
      className={`${
        offset % 2 === 0 ? 'bg-gray-50' : 'bg-white'
      } px-2 py-1 flex flex-row sm:px-6 border-l-4 mb-1 text-gray-900 ${color}`}>
      <dt className="font-medium text-gray-500 w-6/12">{fact.name}</dt>
      <dd className="w-6/12 mt-1 items-start sm:mt-0 truncate">
        <Tooltip value={`${t('terms.score')}: ${fact.score}`}>
          <span className="w-6 inline-block text-center">
            {fact.value !== null && fact.data_type === 'boolean' && (
              <Icon
                className={`${
                  fact.value === 'true' ? 'text-green-600' : 'text-red-600'
                }`}
                icon={`fas ${fact.value === 'true' ? 'check' : 'times-circle'}`}
              />
            )}
            {fact.value !== null &&
              fact.data_type === 'string' &&
              fact.fact_type === 'enum' &&
              fact.icon_class !== null && <Icon icon={fact.icon_class} />}
          </span>
          {fact.value !== null && fact.data_type !== 'boolean' && fact.value}
          {fact.value !== null &&
          fact.ui_options.includes('display-as-percentage')
            ? '%'
            : ''}
          {fact.value === null && (
            <span className="italic text-red-800 text-xs font-light">
              {t('common.notSet')}
            </span>
          )}
        </Tooltip>
      </dd>
    </div>
  )
}
Fact.propTypes = {
  fact: PropTypes.object.isRequired,
  offset: PropTypes.number.isRequired
}

function Display({ project, onEditClick, shouldGrow }) {
  const { t } = useTranslation()
  let lastUpdated = 0
  return (
    <Card className={`flex flex-col ${shouldGrow ? 'h-full' : ''}`}>
      <h2 className="font-medium mb-2">{t('project.projectFacts')}</h2>
      <dl className="lg:ml-4 my-3">
        {project.facts.map((fact, offset) => {
          const updated = Date.parse(fact.recorded_at)
          if (updated > lastUpdated) lastUpdated = updated
          return (
            <Fact
              key={`fact-${fact.fact_type_id}`}
              fact={fact}
              offset={offset}
            />
          )
        })}
      </dl>
      <div className="flex-grow flex flex-row items-end">
        <div className="flex-grow flex items-center mt-2">
          {lastUpdated > 0 && (
            <div className="flex-1 text-xs italic">
              {t('common.lastUpdated', {
                date: new Intl.DateTimeFormat('en-US').format(lastUpdated)
              })}
            </div>
          )}
          {project.archived === false && (
            <div className="flex-1 text-xs text-right">
              <Button onClick={onEditClick}>
                <Icon icon="fas edit" className="mr-2" />
                {t('project.updateFacts')}
              </Button>
            </div>
          )}
        </div>
      </div>
    </Card>
  )
}
Display.propTypes = {
  project: PropTypes.object.isRequired,
  onEditClick: PropTypes.func.isRequired,
  shouldGrow: PropTypes.bool.isRequired
}

function Facts({
  project,
  factTypes,
  editing,
  onEditing,
  refresh,
  shouldGrow
}) {
  if (editing)
    return (
      <EditFacts
        projectId={project.id}
        facts={project.facts}
        factTypes={factTypes}
        onEditFinished={(refreshProject) => {
          onEditing(false)
          if (refreshProject === true) refresh()
        }}
      />
    )
  return (
    <Display
      project={project}
      shouldGrow={shouldGrow}
      onEditClick={() => onEditing(true)}
    />
  )
}
Facts.propTypes = {
  project: PropTypes.object.isRequired,
  factTypes: PropTypes.arrayOf(PropTypes.object).isRequired,
  editing: PropTypes.bool.isRequired,
  onEditing: PropTypes.func.isRequired,
  refresh: PropTypes.func.isRequired,
  shouldGrow: PropTypes.bool.isRequired
}
export { Facts }
