import PropTypes from 'prop-types'
import React from 'react'

import { Badge } from '../'

class ScoreBadge extends React.PureComponent {
  render() {
    let color = 'red'
    if (this.props.value === 0) color = 'gray'
    if (this.props.value > 69) color = 'yellow'
    if (this.props.value > 89) color = 'green'
    return (
      <Badge className="text-sm" color={color}>
        {this.props.value.toLocaleString()}
      </Badge>
    )
  }
}
ScoreBadge.propTypes = {
  value: PropTypes.number.isRequired
}
export { ScoreBadge }
