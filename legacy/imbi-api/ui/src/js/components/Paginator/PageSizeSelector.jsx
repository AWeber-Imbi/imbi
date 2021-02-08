import React, { Fragment } from 'react'
import PropTypes from 'prop-types'
import { useTranslation } from 'react-i18next'

import { Context } from './Context'

const pageSizes = [10, 25, 50, 100]

function PageSizeSelector({ display }) {
  const { t } = useTranslation()
  return (
    <Context.Consumer>
      {(context) => (
        <div className="align-middle flex-1 p-2 text-sm text-gray-700 space-x-2 text-center">
          {display && (
            <Fragment>
              <span>{t('common.pageSize')}:</span>
              {pageSizes.map((size, index) => {
                return (
                  <Fragment key={`page-size-${size}`}>
                    {size === context.pageSize && <span className="font-semibold underline text-blue-700">{size}</span>}
                    {size !== context.pageSize && (
                      <button
                        className="text-gray-700 hover:text-blue-700"
                        onClick={(event) => {
                          event.preventDefault()
                          context.setPageSize(size)
                        }}>
                        {size}
                      </button>
                    )}
                  </Fragment>
                )
              })}
            </Fragment>
          )}
        </div>
      )}
    </Context.Consumer>
  )
}
PageSizeSelector.defaultProps = {
  display: false
}
PageSizeSelector.propTypes = {
  display: PropTypes.bool
}
export { PageSizeSelector }
