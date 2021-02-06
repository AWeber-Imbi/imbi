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
  submitButtonText,
  title
}) {
  return (
    <div className="flex-grow flex flex-row px-6 py-4 w-full">
      <div className="flex-shrink pr-20 text-gray-600">
        <h1 className="inline-block text-xl mb-3 whitespace-nowrap">
          <Icon icon={icon} className="mr-2" />
          {title}
        </h1>
        <SideBar links={sideBarLinks} />
      </div>
      <div className="flex-auto bg-white max-w-screen-lg p-5 rounded-lg text-gray-700">
        {errorMessage !== null && (
          <Alert className="mb-3" level="error">
            {errorMessage}
          </Alert>
        )}
        {children}
        <form onSubmit={onSubmit}>
          <Footer disabled={disabled} instructions={instructions}>
            {submitButtonText}
          </Footer>
        </form>
      </div>
    </div>
  )
}
MultiSectionForm.defaultProps = {
  disabled: false,
  errorMessage: null,
  icon: 'fas file-alt'
}
MultiSectionForm.propTypes = {
  children: PropTypes.oneOfType([
    PropTypes.arrayOf(PropTypes.element),
    PropTypes.element,
    PropTypes.string
  ]),
  disabled: PropTypes.bool,
  errorMessage: PropTypes.string,
  footerButtonText: PropTypes.string,
  icon: PropTypes.string.isRequired,
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
  submitButtonText: PropTypes.string,
  title: PropTypes.string.isRequired
}
export { MultiSectionForm }
