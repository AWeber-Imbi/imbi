import PropTypes from 'prop-types'
import React from 'react'
import ReactMarkdown from 'react-markdown'

class Link extends React.PureComponent {
  render() {
    return (
      <a
        href={this.props.href}
        className="text-blue-600 hover:text-blue-800"
        rel="noreferrer"
        target="_blank">
        {this.props.children}
      </a>
    )
  }
}
Link.propTypes = {
  children: PropTypes.oneOfType([
    PropTypes.element,
    PropTypes.arrayOf(PropTypes.element),
    PropTypes.string
  ]),
  href: PropTypes.string
}

class Markdown extends React.PureComponent {
  render() {
    return (
      <ReactMarkdown className={this.className} renderers={{ link: Link }}>
        {this.children}
      </ReactMarkdown>
    )
  }
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
