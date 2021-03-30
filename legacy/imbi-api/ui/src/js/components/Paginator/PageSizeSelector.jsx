import PropTypes from 'prop-types'
import React, { Fragment, useContext } from 'react'
import { useTranslation } from 'react-i18next'

import { Context } from './Context'

const pageSizes = [10, 25, 50, 100]

function PageSizeSelector({ display }) {
  const context = useContext(Context)
  const { t } = useTranslation()
  if (!display) return <div className="flex-1" />
  return (
    <Fragment>
      <span>{t('paginator.pageSize')}:</span>
      {pageSizes.map((size) => {
        return (
          <Fragment key={`page-size-${size}`}>
            {size === context.pageSize && (
              <span className="font-semibold underline text-blue-700">
                {size}
              </span>
            )}
            {size !== context.pageSize && (
              <button
                className="text-gray-700 hover:text-blue-700"
                onClick={(event) => {
                  event.preventDefault()
                  if (size !== context.pageSize) context.setPageSize(size)
                }}>
                {size}
              </button>
            )}
          </Fragment>
        )
      })}
    </Fragment>
  )
}
PageSizeSelector.defaultProps = {
  display: false
}
PageSizeSelector.propTypes = {
  display: PropTypes.bool
}
export { PageSizeSelector }
