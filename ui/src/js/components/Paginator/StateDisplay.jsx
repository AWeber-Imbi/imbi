import PropTypes from 'prop-types'
import React from 'react'
import { useTranslation } from 'react-i18next'

import { Context } from './Context'

function StateDisplay({ nounSingular, nounPlural }) {
  const { t } = useTranslation()
  return (
    <Context.Consumer>
      {(context) =>
        t('common.paginatorPosition', {
          startRecord: context.offset + 1,
          endRecord: Math.min(
            context.itemCount,
            context.currentPage * context.pageSize
          ).toLocaleString(),
          totalRecords: context.itemCount.toLocaleString(),
          noun: context.itemCount === 1 ? t(nounSingular) : t(nounPlural)
        })
      }
    </Context.Consumer>
  )
}
StateDisplay.defaultProps = {
  nounSingular: 'terms.record',
  nounPlural: 'terms.records'
}
StateDisplay.propTypes = {
  display: PropTypes.bool,
  nounSingular: PropTypes.string,
  nounPlural: PropTypes.string
}
export { StateDisplay }
