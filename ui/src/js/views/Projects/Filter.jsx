import PropTypes from 'prop-types'
import React from 'react'
import Select from 'react-select'
import { useTranslation } from 'react-i18next'

import { Form, Icon } from '../../components'
import theme from '../../theme'
import { Link } from 'react-router-dom'

function Filter({
  disabled,
  namespaces,
  projectTypes,
  setFilterValues,
  values
}) {
  const { t } = useTranslation()
  const includeArchived = values.include_archived
  const namespace = namespaces.filter(
    (v) => v.value.toString() === values.namespace_id
  )
  const projectType = projectTypes.filter(
    (v) => v.value.toString() === values.project_type_id
  )
  const styles = {
    control: (provided) => {
      return {
        ...provided,
        zIndex: theme.zIndex['10'],
        fontFamily: theme.fontFamily.sans.join(','),
        fontSize: theme.fontSize.sm,
        borderColor: theme.colors.gray['300'],
        borderRadius: theme.borderRadius.md,
        borderWidth: theme.borderWidth['2xl'],
        outline: 'none',
        boxShadow: 'none'
      }
    },
    input: (provided) => {
      //console.log(provided)
      return {
        ...provided,
        outline: 'none',
        '&:hover': 'none'
      }
    },
    menu: (provided) => {
      //console.log(provided)
      return {
        ...provided,
        borderRadius: 0,
        fontFamily: theme.fontFamily.sans.join(','),
        fontSize: theme.fontSize.sm
      }
    },
    option: (provided, state) => {
      //console.log(provided)
      return {
        ...provided,
        backgroundColor: state.isSelected
          ? theme.colors.blue['500']
          : theme.colors.white,
        '&:hover': {
          ...provided['&:hover'],
          backgroundColor: theme.colors.blue['700'],
          color: theme.colors.white
        }
      }
    }
  }

  function onChange(key, value) {
    const newValues = {
      ...values,
      [key]: value
    }
    if (values !== newValues) setFilterValues(newValues)
  }

  return (
    <form className="flex flex-row items-center md:space-x-2 text-gray-500 sm:w-full md:w-full">
      <Icon icon="fas filter" className="hidden md:inline-block ml-2" />
      <label className="hidden lg:inline-block pr-2">
        {t('common.filter')}
      </label>
      <Select
        className="border-gray-200 flex-auto sm:mr-2 shadow text-gray-600"
        isClearable
        isDisabled={disabled}
        isSearchable={false}
        name="namespace_id"
        options={namespaces}
        onChange={(option) => {
          onChange('namespace_id', option && option.value.toString())
        }}
        placeholder={t('terms.namespace')}
        styles={styles}
        value={namespace}
      />
      <input
        className="border-0 flex-1 form-input m-0 placeholder-gray-500 shadow text-gray-500"
        type="text"
        autoComplete="off"
        disabled={disabled}
        name="project_name"
        placeholder={t('common.name')}
        style={{ padding: '.575rem' }}
        onBlur={(event) => {
          onChange('name', event.target.value)
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter') onChange('name', event.target.value)
        }}
      />
      <Select
        className="border-gray-200 flex-auto sm:mr-2 shadow text-gray-600"
        isClearable
        isDisabled={disabled}
        isSearchable={false}
        name="project_type_id"
        options={projectTypes}
        onChange={(option) => {
          onChange('project_type_id', option && option.value.toString())
        }}
        placeholder={t('terms.projectType')}
        styles={styles}
        value={projectType}
      />
      <Link
        to="/ui/reports/project-type-definitions"
        className="hidden md:inline-block pl-2 hover:text-blue-600"
        title={t('reports.projectTypeDefinitions.title')}>
        <Icon icon="fas book-open" />
      </Link>
      <div className="hidden md:inline-block pl-2 pt-1">
        <Form.Toggle
          name="archived"
          disabled={disabled}
          onChange={(name, value) => {
            setFilterValues({ ...values, include_archived: value })
          }}
          title={t('projects.includeArchived')}
          value={includeArchived}
        />
      </div>
      <label className="hidden lg:inline-block whitespace-nowrap">
        {t('projects.includeArchived')}
      </label>
    </form>
  )
}
Filter.defaultProps = {
  namespaces: [],
  projectTypes: []
}
Filter.propTypes = {
  disabled: PropTypes.bool,
  namespaces: PropTypes.arrayOf(
    PropTypes.exact({ label: PropTypes.string, value: PropTypes.number })
  ),
  projectTypes: PropTypes.arrayOf(
    PropTypes.exact({ label: PropTypes.string, value: PropTypes.number })
  ),
  setFilterValues: PropTypes.func,
  values: PropTypes.object
}
export { Filter }
