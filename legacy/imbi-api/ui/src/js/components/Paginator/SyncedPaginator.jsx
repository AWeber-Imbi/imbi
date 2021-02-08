import PropTypes from 'prop-types'
import React from 'react'

import { Buttons } from './Buttons'
import { PageSizeSelector } from './PageSizeSelector'
import { StateDisplay } from './StateDisplay'

function Paginator({
  positionNounSingular,
  positionNounPlural,
  showPageSizeSelector,
  showStateDisplay
}) {
  return (
    <div className="align-middle flex flex-column mt-3">
      <StateDisplay
        display={showStateDisplay}
        nounPlural={positionNounPlural}
        nounSingular={positionNounSingular}
      />
      <PageSizeSelector display={showPageSizeSelector} />
      <Buttons />
    </div>
  )
}
Paginator.defaultProps = {
  positionNounSingular: 'terms.record',
  positionNounPlural: 'terms.records',
  showPageSizeSelector: false,
  showStateDisplay: false
}
Paginator.propTypes = {
  positionNounSingular: PropTypes.string,
  positionNounPlural: PropTypes.string,
  showPageSizeSelector: PropTypes.bool,
  showStateDisplay: PropTypes.bool
}
export { Paginator }
