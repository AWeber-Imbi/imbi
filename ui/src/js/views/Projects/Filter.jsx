import PropTypes from 'prop-types'
import React from 'react'
import Select from 'react-select'
import { useTranslation } from 'react-i18next'

import { Form, Icon } from '../../components'
import theme from '../../theme'

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
        borderWidth: theme.borderWidth['1'],
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

  function onChange(key, option) {
    const newValues = {
      ...values,
      [key]: option === null ? null : option.value.toString()
    }
    if (values !== newValues) setFilterValues(newValues)
  }

  return (
    <form className="flex items-center space-x-2 text-gray-600 ml-2">
      <Icon icon="fas filter" />
      <label className="flex-shrink">{t('common.filter')}</label>
      <Select
        className="flex-1"
        isClearable
        isDisabled={disabled}
        isSearchable={false}
        name="namespace_id"
        options={namespaces}
        onChange={(values) => {
          onChange('namespace_id', values)
        }}
        placeholder={t('terms.namespace')}
        styles={styles}
        value={namespace}
      />
      <Select
        className="flex-1"
        isClearable
        isDisabled={disabled}
        isSearchable={false}
        name="project_type_id"
        options={projectTypes}
        onChange={(values) => {
          onChange('project_type_id', values)
        }}
        placeholder={t('terms.projectType')}
        styles={styles}
        value={projectType}
      />
      <div className="flex-shrink flex items-center px-4">
        <Form.Toggle
          name="archived"
          className="flex-shrink"
          disabled={disabled}
          onChange={(name, value) => {
            setFilterValues({ ...values, include_archived: value })
          }}
          value={includeArchived}
        />
        <label
          htmlFor="archived"
          className="flex-shrink text-sm font-medium ml-2 text-gray-700 whitespace-nowrap">
          Include archived projects
        </label>
      </div>
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
