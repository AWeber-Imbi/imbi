import PropTypes from 'prop-types'
import React from 'react'

function Footer({ columns }) {
  return (
    <tfoot className="bg-gray-50">
      <tr>
        <td className="bg-gray-50 h-2" colSpan={columns}>
          {' '}
        </td>
      </tr>
    </tfoot>
  )
}
Footer.propTypes = {
  columns: PropTypes.number.isRequired
}

export { Footer }
