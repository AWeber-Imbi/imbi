import PropTypes from 'prop-types'
import React, { Fragment } from 'react'

import { Button, Icon } from '../'

function PageHeader({
  buttonClass,
  buttonDestination,
  buttonIcon,
  buttonOnClick,
  buttonTitle,
  pageIcon,
  pageTitle
}) {
  return (
    <div className={buttonTitle && 'grid grid-cols-2'}>
      <h1 className="inline-block text-gray-600 text-xl">
        {pageIcon && <Icon icon={pageIcon} className="ml-2 mr-2" />}
        {pageTitle}
      </h1>
      {buttonTitle && (
        <div className="text-right">
          <Button
            className={buttonClass}
            destination={buttonDestination}
            onClick={buttonOnClick}>
            <Fragment>
              <Icon className="mr-3" icon={buttonIcon} />
              {buttonTitle}
            </Fragment>
          </Button>
        </div>
      )}
    </div>
  )
}

PageHeader.defaultProps = {
  buttonClass: 'btn-green',
  buttonIcon: 'fas plus-circle'
}

PageHeader.propTypes = {
  buttonClass: PropTypes.string,
  buttonDestination: PropTypes.string,
  buttonIcon: PropTypes.string,
  buttonOnClick: PropTypes.func,
  buttonTitle: PropTypes.string,
  pageIcon: PropTypes.string,
  pageTitle: PropTypes.string.isRequired
}

export { PageHeader }
