import PropTypes from 'prop-types'
import React from 'react'

import { Chart, Modal } from '../../../components/'

class PopupGraph extends React.PureComponent {
  render() {
    const data = {
      labels: this.props.data.map((entry) => {
        return entry.date
      }),
      datasets: [
        {
          fill: false,
          backgroundColor: 'rgb(0, 99, 255)',
          borderColor: 'rgba(0, 99, 255)',
          data: this.props.data.map((entry) => {
            return entry.value
          }),
          label: this.props.label,
          radius: 0
        }
      ]
    }
    return (
      <Modal onClose={this.props.onClose}>
        <Modal.Title
          icon={this.props.icon}
          showClose={true}
          onClose={this.props.onClose}>
          {this.props.title}
        </Modal.Title>
        <Chart.Line data={data} minValue={0} maxValue={100} />
      </Modal>
    )
  }
}
PopupGraph.propTypes = {
  title: PropTypes.string.isRequired,
  icon: PropTypes.string,
  label: PropTypes.string.isRequired,
  data: PropTypes.arrayOf(PropTypes.object).isRequired,
  onClose: PropTypes.func
}
export { PopupGraph }
