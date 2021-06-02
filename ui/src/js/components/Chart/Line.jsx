import { Line } from 'react-chartjs-2'
import PropTypes from 'prop-types'
import React from 'react'

class LineChart extends React.PureComponent {
  render() {
    return (
      <div className={this.props.className}>
        <Line
          data={this.props.data}
          height={this.props.height}
          width={this.props.width}
          options={{
            animation: false,
            responsive: true,
            plugins: {
              legend: {
                display: false
              }
            },
            scales: {
              y: {
                suggestedMin: this.props.minValue,
                suggestedMax: this.props.maxValue
              }
            }
          }}
          type="line"
        />
      </div>
    )
  }
}
LineChart.propTypes = {
  className: PropTypes.string,
  data: PropTypes.oneOfType([PropTypes.object, PropTypes.array]),
  height: PropTypes.number,
  width: PropTypes.number,
  minValue: PropTypes.number,
  maxValue: PropTypes.number
}
export { LineChart }
