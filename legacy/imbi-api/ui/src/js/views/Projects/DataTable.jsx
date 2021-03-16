import PropTypes from 'prop-types'
import React from 'react'
import { useTranslation } from 'react-i18next'

import { Badge, Paginator, Table } from '../../components'

function DataTable({
  data,
  offset,
  onRowClick,
  onSortDirection,
  pageSize,
  rowCount,
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
      currentPage={offset + 1}
      itemCount={rowCount}
      itemsPerPage={pageSize}
      setCurrentPage={(currentPage) => setOffset(currentPage - 1)}
      setPageSize={setPageSize}>
      <Table columns={columns} data={data} onRowClick={onRowClick} />
      <Paginator.Controls showPageSizeSelector={true} showStateDisplay={true} />
    </Paginator.Container>
  )
}
DataTable.propTypes = {
  data: PropTypes.arrayOf(PropTypes.object),
  offset: PropTypes.number,
  onRowClick: PropTypes.func,
  onSortDirection: PropTypes.func,
  pageSize: PropTypes.number,
  rowCount: PropTypes.number,
  setOffset: PropTypes.func,
  setPageSize: PropTypes.func,
  sort: PropTypes.object
}
export { DataTable }
