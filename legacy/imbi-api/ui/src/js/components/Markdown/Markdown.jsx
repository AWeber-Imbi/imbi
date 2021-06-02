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
class UL extends React.PureComponent {
  render() {
    return (
      <ul className="list-disc list-inside space-y-2">{this.props.children}</ul>
    )
  }
}
UL.propTypes = {
  children: PropTypes.any
}

class Markdown extends React.PureComponent {
  static propTypes = {
    children: PropTypes.oneOfType([
      PropTypes.element,
      PropTypes.arrayOf(PropTypes.element),
      PropTypes.string
    ]),
    className: PropTypes.string
  }

  render() {
    return (
      <ReactMarkdown
        className={this.props.className}
        components={{
          a: ({ ...props }) => <Link {...props} />,
          ul: ({ ...props }) => <UL {...props} />
        }}>
        {this.props.children}
      </ReactMarkdown>
    )
  }
}
export { Markdown }
