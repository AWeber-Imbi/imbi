import PropTypes from 'prop-types'
import React, { Fragment } from 'react'

function Section({ name, title, firstSection, children }) {
  return (
    <Fragment>
      <div className={`pb-2 ${firstSection ? '' : ' mt-10'}`}>
        <h3 className="text-lg leading-6 font-medium">
          <a name={name}>{title}</a>
        </h3>
      </div>
      <div className="border-t border-gray-300 w-full pl-5">{children}</div>
    </Fragment>
  )
}
Section.defaultProps = {
  firstSection: false
}
Section.propTypes = {
  name: PropTypes.string.isRequired,
  title: PropTypes.string.isRequired,
  firstSection: PropTypes.bool,
  children: PropTypes.oneOfType([
    PropTypes.arrayOf(PropTypes.element),
    PropTypes.element,
    PropTypes.string
  ])
}
export { Section }
