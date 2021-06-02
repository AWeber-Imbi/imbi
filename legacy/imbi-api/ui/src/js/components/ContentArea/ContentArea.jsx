import PropTypes from 'prop-types'
import React from 'react'

import { setDocumentTitle } from '../../utils'

import { PageHeader } from './PageHeader'

function ContentArea({
  buttonClass,
  buttonDestination,
  buttonIcon,
  buttonOnClick,
  buttonTitle,
  children,
  className,
  pageIcon,
  pageTitle,
  setPageTitle,
  showHeader
}) {
  if (setPageTitle === true) setDocumentTitle(pageTitle)
  return (
    <div
      className={`p-4 space-y-3 ${className !== undefined ? className : ''}`}>
      {showHeader && (
        <PageHeader
          buttonClass={buttonClass}
          buttonDestination={buttonDestination}
          buttonIcon={buttonIcon}
          buttonOnClick={buttonOnClick}
          buttonTitle={buttonTitle}
          pageIcon={pageIcon}
          pageTitle={pageTitle}
        />
      )}
      {children}
    </div>
  )
}
ContentArea.defaultProps = {
  showHeader: true,
  setPageTitle: true
}
ContentArea.propTypes = {
  children: PropTypes.oneOfType([
    PropTypes.arrayOf(PropTypes.node),
    PropTypes.node,
    PropTypes.func
  ]),
  className: PropTypes.string,
  pageIcon: PropTypes.string,
  pageTitle: PropTypes.string.isRequired,
  buttonClass: PropTypes.string,
  buttonDestination: PropTypes.string,
  buttonIcon: PropTypes.string,
  buttonOnClick: PropTypes.func,
  buttonTitle: PropTypes.string,
  showHeader: PropTypes.bool,
  setPageTitle: PropTypes.bool
}
export { ContentArea }
