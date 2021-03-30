import React, { useContext } from 'react'
import { useTranslation } from 'react-i18next'

import { Icon } from '../Icon/Icon'

import { Context } from './Context'

export const buttonStyle =
  'relative inline-flex items-center px-2 py-2 border text-sm font-medium'
export const availableButton = `${buttonStyle}  border-gray-300 bg-white text-gray-700 hover:bg-gray-50 hover:text-blue-700`
export const disabledButton = `${buttonStyle} border-gray-300 bg-gray-50 text-sm font-medium text-gray-500`
export const selectedButton = `${buttonStyle} border-blue-400 bg-blue-500 text-white`

export function Buttons() {
  const context = useContext(Context)
  const { t } = useTranslation()
  return (
    <nav
      className="relative z-0 inline-flex shadow-sm -space-x-px"
      aria-label="Controls">
      {context.itemCount > 0 && context.currentPage === 1 && (
        <div className={`${disabledButton} rounded-l-md`}>
          <span className="sr-only">{t('paginator.previous')}</span>
          <Icon icon="fas chevron-left" />
        </div>
      )}
      {context.itemCount > 0 && context.currentPage > 1 && (
        <button
          className={`${availableButton} rounded-l-md`}
          onClick={(event) => {
            event.preventDefault()
            context.setCurrentPage(context.prevPage)
          }}>
          <span className="sr-only">{t('paginator.previous')}</span>
          <Icon icon="fas chevron-left" />
        </button>
      )}
      {context.currentPage - context.adjacentPages > 1 && (
        <button
          className={availableButton}
          onClick={(event) => {
            event.preventDefault()
            context.setCurrentPage(1)
          }}>
          1
        </button>
      )}
      {context.currentPage - context.adjacentPages > 1 && (
        <div className={disabledButton}>&hellip;</div>
      )}
      {context.pages.map((page) => {
        if (page === context.currentPage) {
          return (
            <div className={selectedButton} key={`pagination-page-${page}`}>
              {page}
            </div>
          )
        }
        return (
          <button
            className={availableButton}
            key={`pagination-page-${page}`}
            onClick={(event) => {
              event.preventDefault()
              context.setCurrentPage(page)
            }}>
            {page}
          </button>
        )
      })}
      {context.pageCount - context.lastPage > 1 && (
        <div className={disabledButton}>&hellip;</div>
      )}
      {context.pageCount - context.lastPage > 0 && (
        <button
          className={availableButton}
          onClick={(event) => {
            event.preventDefault()
            context.setCurrentPage(context.pageCount)
          }}>
          {context.pageCount}
        </button>
      )}
      {context.currentPage === context.pageCount && (
        <div className={`${disabledButton} rounded-r-md`}>
          <span className="sr-only">{t('paginator.next')}</span>
          <Icon icon="fas chevron-right" />
        </div>
      )}
      {context.currentPage < context.pageCount && (
        <button
          className={`${availableButton} rounded-r-md`}
          onClick={(event) => {
            event.preventDefault()
            context.setCurrentPage(context.nextPage)
          }}>
          <span className="sr-only">{t('paginator.next')}</span>
          <Icon icon="fas chevron-right" />
        </button>
      )}
    </nav>
  )
}
