import PropTypes from 'prop-types'
import React from 'react'
import { useTranslation } from 'react-i18next'

import { Badge, Paginator, Table } from '../../components'

function DataTable({
  data,
  disabled,
  offset,
  onSortDirection,
  pageSize,
  rowCount,
  rowURL,
  setOffset,
  setPageSize,
  sort
}) {
  const { t } = useTranslation()
  const columns = [
    {
      title: t('terms.namespace'),
      name: 'namespace',
      sortCallback: onSortDirection,
      sortDirection: sort.namespace !== undefined ? sort.namespace : null,
      type: 'text',
      tableOptions: {
        className: 'truncate',
        headerClassName: 'w-3/12'
      }
    },
    {
      title: t('terms.name'),
      name: 'name',
      sortCallback: onSortDirection,
      sortDirection: sort.name !== undefined ? sort.name : null,
      type: 'text',
      tableOptions: {
        className: 'truncate',
        headerClassName: 'w-3/12'
      }
    },
    {
      title: t('terms.projectType'),
      name: 'project_type',
      sortCallback: onSortDirection,
      sortDirection: sort.project_type !== undefined ? sort.project_type : null,
      type: 'text',
      tableOptions: {
        className: 'truncate',
        headerClassName: 'w-3/12'
      }
    },
    {
      title: t('terms.healthScore'),
      name: 'project_score',
      sortCallback: onSortDirection,
      sortDirection:
        sort.project_score !== undefined ? sort.project_score : null,
      type: 'text',
      tableOptions: {
        className: 'text-center',
        headerClassName: 'w-2/12 text-center',
        lookupFunction: (value) => {
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
      }
    }
  ]

  return (
    <Paginator.Container
      currentPage={offset / pageSize + 1}
      itemCount={rowCount}
      itemsPerPage={pageSize}
      setCurrentPage={(currentPage) => {
        const value = (currentPage - 1) * pageSize
        setOffset(value)
      }}
      setPageSize={setPageSize}>
      <Table
        columns={columns}
        data={data}
        disabled={disabled}
        rowURL={rowURL}
      />
      <Paginator.Controls
        disabled={disabled}
        showPageSizeSelector={true}
        showStateDisplay={true}
      />
    </Paginator.Container>
  )
}
DataTable.propTypes = {
  data: PropTypes.arrayOf(PropTypes.object),
  disabled: PropTypes.bool,
  offset: PropTypes.number,
  onSortDirection: PropTypes.func,
  pageSize: PropTypes.number,
  rowCount: PropTypes.number,
  rowURL: PropTypes.func,
  setOffset: PropTypes.func,
  setPageSize: PropTypes.func,
  sort: PropTypes.object
}
export { DataTable }
