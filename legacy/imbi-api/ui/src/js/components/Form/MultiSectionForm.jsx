import PropTypes from 'prop-types'
import React from 'react'

import { Alert, Icon } from '..'
import { Footer } from './Footer'
import { SideBar } from './SideBar'

function MultiSectionForm({
  children,
  disabled,
  errorMessage,
  icon,
  instructions,
  onSubmit,
  sideBarLinks,
  sideBarTitle,
  submitButtonText
}) {
  return (
    <div className="flex-grow flex flex-row px-6 py-4 w-full">
      <div className="flex-shrink mt-2 pr-20 text-gray-600">
        {sideBarTitle && (
          <h1 className="text-medium text-lg mb-2">
            {icon && <Icon icon={icon} className="mr-2" />}
            {sideBarTitle}
          </h1>
        )}
        <SideBar links={sideBarLinks} />
      </div>
      <div className="flex-auto bg-white max-w-screen-lg p-5 rounded-lg space-y-3 text-gray-700">
        {errorMessage !== null && (
          <Alert className="mb-3" level="error">
            {errorMessage}
          </Alert>
        )}
        {children}
        <form onSubmit={onSubmit}>
          {submitButtonText && (
            <Footer disabled={disabled} instructions={instructions}>
              {submitButtonText}
            </Footer>
          )}
        </form>
      </div>
    </div>
  )
}
MultiSectionForm.defaultProps = {
  disabled: false,
  errorMessage: null
}
MultiSectionForm.propTypes = {
  children: PropTypes.oneOfType([
    PropTypes.arrayOf(PropTypes.element),
    PropTypes.element,
    PropTypes.string
  ]),
  disabled: PropTypes.bool,
  errorMessage: PropTypes.string,
  icon: PropTypes.string,
  instructions: PropTypes.oneOfType([
    PropTypes.arrayOf(PropTypes.element),
    PropTypes.element,
    PropTypes.string
  ]),
  onSubmit: PropTypes.func,
  sideBarLinks: PropTypes.arrayOf(
    PropTypes.exact({
      href: PropTypes.string.isRequired,
      label: PropTypes.string.isRequired
    })
  ),
  sideBarTitle: PropTypes.string,
  submitButtonText: PropTypes.string
}
export { MultiSectionForm }
