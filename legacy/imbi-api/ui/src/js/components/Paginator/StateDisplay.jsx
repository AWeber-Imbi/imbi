import PropTypes from 'prop-types'
import React from 'react'
import { useTranslation } from 'react-i18next'

import { Context } from './Context'

function StateDisplay({ display, nounSingular, nounPlural }) {
  const { t } = useTranslation()
  return (
    <Context.Consumer>
      {(context) => (
        <div className="align-middle flex-1 p-2 text-sm text-gray-700">
          {display &&
            t('common.paginatorPosition', {
              startRecord: context.offset + 1,
              endRecord: Math.min(
                context.itemCount,
                context.currentPage * context.pageSize
              ).toLocaleString(),
              totalRecords: context.itemCount.toLocaleString(),
              noun: context.itemCount === 1 ? t(nounSingular) : t(nounPlural)
            })}
        </div>
      )}
    </Context.Consumer>
  )
}
StateDisplay.defaultProps = {
  display: false,
  nounSingular: 'terms.record',
  nounPlural: 'terms.records'
}
StateDisplay.propTypes = {
  display: PropTypes.bool,
  nounSingular: PropTypes.string,
  nounPlural: PropTypes.string
}
export { StateDisplay }
