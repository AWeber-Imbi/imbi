import PropTypes from 'prop-types'
import React from 'react'
import SyntaxHighlighter from 'react-syntax-highlighter'
import { github } from 'react-syntax-highlighter/dist/cjs/styles/hljs'

class CodeBlock extends React.PureComponent {
  static propTypes = {
    value: PropTypes.string.isRequired,
    language: PropTypes.string
  }

  static defaultProps = {
    language: null
  }

  render() {
    return (
      <SyntaxHighlighter
        className="p-2 rounded"
        language={this.props.language}
        style={github}>
        {this.props.value}
      </SyntaxHighlighter>
    )
  }
}
export { CodeBlock }
