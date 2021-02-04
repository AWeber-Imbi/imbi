import PropTypes from 'prop-types'
import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'

function Toggle({ name, onChange, value }) {
  const { t } = useTranslation()
  const [toggleOn, setToggleOn] = useState(value)
  return (
    <button
      type="button"
      className={
        (toggleOn ? 'bg-blue-600' : 'bg-gray-200') +
        ' mt-2 relative inline-flex flex-shrink-0 h-5 w-9 border-2 border-transparent rounded-full cursor-pointer transition-colors ease-in-out duration-200 focus:outline-none'
      }
      aria-pressed="false"
      onClick={(event) => {
        event.preventDefault()
        setToggleOn(!toggleOn)
        onChange(name, !toggleOn)
      }}
      title={toggleOn ? t('common.turnOff') : t('common.turnOn')}>
      <span className="sr-only">
        Toggle {toggleOn ? t('common.off') : t('common.on')}
      </span>
      <span
        aria-hidden="true"
        className={
          (toggleOn ? 'translate-x-4' : 'translate-x-0') +
          ' pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform ring-0 transition ease-in-out duration-200'
        }
      />
    </button>
  )
}

Toggle.defaultProps = {
  value: false
}

Toggle.propTypes = {
  name: PropTypes.string.isRequired,
  onChange: PropTypes.func.isRequired,
  value: PropTypes.bool
}

export { Toggle }
