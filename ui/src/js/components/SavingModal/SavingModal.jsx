import PropTypes from 'prop-types'
import React from 'react'
import { useTranslation } from 'react-i18next'

import { Button, Icon, Modal } from '..'

function SavingModal({ title, steps, onSaveComplete }) {
  const { t } = useTranslation()
  const completed = steps.every((element) => element.isComplete === true)
  return (
    <Modal>
      <Modal.Title>{title}</Modal.Title>
      <Modal.Body>
        <ul className="m-5 mb-0">
          {steps.map((step, index) => {
            return (
              <li className="text-gray-500" key={'saving-step-' + index}>
                {index > 0 && (
                  <div className="m-2 border-l border-gray-300 h-3">&nbsp;</div>
                )}
                <div>
                  <Icon
                    icon={step.isComplete ? 'fas check-circle' : 'fas circle'}
                    className={
                      'mr-2 ' +
                      (step.isComplete ? 'text-green-500' : 'text-gray-300')
                    }
                  />
                  {step.isComplete ? step.completedLabel : step.pendingLabel}
                </div>
              </li>
            )
          })}
        </ul>
      </Modal.Body>
      <Modal.Footer>
        <Button
          className={completed ? 'btn-white' : 'btn-disabled'}
          disabled={!completed}
          key="modal-close"
          onClick={onSaveComplete}>
          {t('common.close')}
        </Button>
      </Modal.Footer>
    </Modal>
  )
}

SavingModal.propTypes = {
  title: PropTypes.string.isRequired,
  steps: PropTypes.arrayOf(
    PropTypes.exact({
      isComplete: PropTypes.bool.isRequired,
      pendingLabel: PropTypes.string.isRequired,
      completedLabel: PropTypes.string.isRequired
    })
  ),
  onSaveComplete: PropTypes.func
}

export { SavingModal }
