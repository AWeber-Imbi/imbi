import PropTypes from 'prop-types'
import React from 'react'
import { useTranslation } from 'react-i18next'

import { Icon } from '../'

function Pagination({ currentPage, itemCount, itemsPerPage, onChange }) {
  const { t } = useTranslation()
  const pages = Math.ceil(itemCount / itemsPerPage)
  return (
    <div className="align-middle flex flex-column mt-3">
      <div className="align-middle flex-1 p-2 text-sm text-gray-700">
        {t('common.paginationState', {
          startRecord: currentPage.toLocaleString(),
          endRecord: Math.min(
            itemCount,
            currentPage + itemsPerPage
          ).toLocaleString(),
          totalRecords: itemCount.toLocaleString()
        })}
      </div>
      <div className="flex-1 text-right">
        <nav
          className="relative z-0 inline-flex shadow-sm -space-x-px"
          aria-label="Pagination">
          <button
            className={
              (currentPage === 1 ? 'disabled cursor-not-allowed' : '') +
              'relative inline-flex items-center px-2 py-2 rounded-l-md border border-gray-300 bg-white text-sm font-medium text-gray-500 hover:bg-gray-50'
            }
            disabled={currentPage === 1}
            onClick={(event) => {
              event.preventDefault()
              onChange(1)
            }}>
            <span className="sr-only">{t('common.previous')}</span>
            <Icon icon="fas chevron-left" />
          </button>
          <button
            className={
              (currentPage === 1 ? 'disabled cursor-not-allowed' : '') +
              'relative inline-flex items-center px-4 py-2 border border-gray-300 bg-white text-sm font-medium text-gray-700 hover:bg-gray-50'
            }
            disabled={currentPage === 1}
            onClick={(event) => {
              event.preventDefault()
              onChange(1)
            }}>
            1
          </button>
          <button
            className={
              (currentPage === pages ? 'disabled cursor-not-allowed' : '') +
              'relative inline-flex items-center px-2 py-2 rounded-r-md border border-gray-300 bg-white text-sm font-medium text-gray-500 hover:bg-gray-50'
            }
            disabled={currentPage === pages}
            onClick={(event) => {
              event.preventDefault()
              onChange(pages)
            }}>
            <span className="sr-only">{t('common.next')}</span>
            <Icon icon="fas chevron-right" />
          </button>
        </nav>
      </div>
    </div>
  )
}

Pagination.propTypes = {
  itemCount: PropTypes.number.isRequired,
  currentPage: PropTypes.number.isRequired,
  itemsPerPage: PropTypes.number.isRequired,
  onChange: PropTypes.func.isRequired
}

export { Pagination }
