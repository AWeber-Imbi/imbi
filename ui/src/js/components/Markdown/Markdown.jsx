import PropTypes from 'prop-types'
import React from 'react'
import ReactMarkdown from 'react-markdown'

function Link({ href, children }) {
  return (
    <a
      href={href}
      className="text-blue-600 hover:text-blue-800"
      rel="noreferrer"
      target="_blank">
      {children}
    </a>
  )
}
Link.propTypes = {
  children: PropTypes.oneOfType([
    PropTypes.element,
    PropTypes.arrayOf(PropTypes.element),
    PropTypes.string
  ]),
  href: PropTypes.string
}

function Markdown({ children, className }) {
  return (
    <ReactMarkdown className={className} renderers={{ link: Link }}>
      {children}
    </ReactMarkdown>
  )
}
Markdown.propTypes = {
  children: PropTypes.oneOfType([
    PropTypes.element,
    PropTypes.arrayOf(PropTypes.element),
    PropTypes.string
  ]),
  className: PropTypes.string
}
export { Markdown }
