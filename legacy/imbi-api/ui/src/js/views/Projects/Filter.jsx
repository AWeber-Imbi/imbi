import { onlyUpdateForKeys } from 'recompose'
import PropTypes from 'prop-types'
import React from 'react'
import { useTranslation } from 'react-i18next'

import { Icon, SlimSelect } from '../../components'

function Filter({ namespaces, projectTypes, setFilterValues, values }) {
  const { t } = useTranslation()

  const maxLength = {
    namespaces:
      namespaces
        .map((opt) => opt.label.length)
        .reduce((max, cur) => Math.max(max, cur)) / 2.05,
    projectTypes:
      projectTypes
        .map((opt) => opt.label.length)
        .reduce((max, cur) => Math.max(max, cur)) / 1.9
  }

  function onChange(key, value) {
    const newValues = { ...values }
    if (value === null) {
      delete newValues[key]
    } else {
      newValues[key] = value
    }
    if (values !== newValues) setFilterValues(newValues)
  }

  return (
    <form className="flex items-center space-x-2 text-gray-600 ml-2">
      <Icon icon="fas filter" />
      <label className="flex-shrink">{t('common.filter')}</label>
      <SlimSelect
        className="flex-shrink formInput text-xs"
        onChange={(value) => onChange('namespace_id', value)}
        placeholder={t('terms.namespace')}
        style={{ width: `${maxLength.namespaces}rem` }}
        value={values.namespace === null ? undefined : values.namespace}>
        {namespaces.map((option) => {
          return (
            <option
              key={`namespace-${option.value}`}
              value={option.value.toString()}>
              {option.label}
            </option>
          )
        })}
      </SlimSelect>
      <SlimSelect
        className="flex-shrink formInput text-xs"
        onChange={(value) => onChange('project_type_id', value)}
        style={{ width: `${maxLength.projectTypes}rem` }}
        placeholder={t('terms.projectType')}
        value={values.project_type === null ? undefined : values.project_type}>
        {projectTypes &&
          projectTypes.map((option) => {
            return (
              <option
                key={`projectType-${option.value}`}
                value={option.value.toString()}>
                {option.label}
              </option>
            )
          })}
      </SlimSelect>
    </form>
  )
}
Filter.defaultProps = {
  namespaces: [],
  projectTypes: []
}
Filter.propTypes = {
  namespaces: PropTypes.arrayOf(
    PropTypes.exact({ label: PropTypes.string, value: PropTypes.number })
  ),
  projectTypes: PropTypes.arrayOf(
    PropTypes.exact({ label: PropTypes.string, value: PropTypes.number })
  ),
  setFilterValues: PropTypes.func,
  values: PropTypes.object
}
const PureFilter = onlyUpdateForKeys(['values'])(Filter)
export { PureFilter as Filter }
