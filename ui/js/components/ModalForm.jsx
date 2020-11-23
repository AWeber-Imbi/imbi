import React, { useState } from 'react'

import {
    Button,
    FormGroup,
    Label,
    Modal,
    ModalBody,
    ModalFooter,
    ModalHeader,
} from 'reactstrap'

import { isFunction } from '../utils'

import Alert from './Alert'
import { Select } from './Form/'

export default function (props) {
    const [submitting, setSubmitting] = useState(false)
    const [errorMessage, setErrorMessage] = useState(undefined)
    const [invalidFields, setInvalidFields] = useState([])
    const [values, setValues] = useState(props.values)

    function columnError(name) {
        return invalidFields.findIndex((x) => x == name) != -1
    }

    function onSubmit(e) {
        e.preventDefault()
        setSubmitting(true)
        let newValues = { ...values }

        props.columns.forEach((column) => {
            if (
                column.default !== undefined &&
                newValues[column.name] === undefined
            )
                values[column.name] = isFunction(column.default)
                    ? column.default()
                    : column.default
        })

        props.createCallback(newValues, (message, invalidFields) => {
            setSubmitting(false)
            setErrorMessage(message)
            setInvalidFields(invalidFields)
        })
    }

    return (
        <Modal isOpen={true} toggle={props.close} backdrop centered>
            <form onSubmit={onSubmit} name="addForm">
                <ModalHeader toggle={props.close}>
                    <span
                        className={
                            props.addIcon ? props.addIcon : 'fas fa-folder-plus'
                        }
                    />
                    Add {props.itemTitle}
                </ModalHeader>
                <ModalBody>
                    <Alert color="danger">{errorMessage}</Alert>
                    <FormGroups
                        {...props}
                        changeCallback={setValues}
                        columnError={columnError}
                        values={values}
                    />
                </ModalBody>
                <ModalFooter>
                    <Button color="secondary" onClick={props.close}>
                        Close
                    </Button>
                    <Button
                        color="primary"
                        type="submit"
                        disabled={submitting === true}
                    >
                        {submitting === true ? 'Saving...' : 'Save'}
                    </Button>
                </ModalFooter>
            </form>
        </Modal>
    )
}

function FormGroupItem(props) {
    function onChange(e) {
        props.changeCallback({
            ...props.values,
            [e.target.name]: e.target.value,
        })
    }
    const inputId = 'add' + props.name.replace(/ /g, '')
    return (
        <>
            {props.hidden !== true && (
                <FormGroup>
                    <Label for={inputId}>{props.title}</Label>
                    {(props.type === undefined || props.type == 'text') && (
                        <input
                            type="text"
                            className={
                                'form-control' +
                                (props.columnError(props.name)
                                    ? ' is-invalid'
                                    : '')
                            }
                            name={props.name}
                            id={inputId}
                            onChange={onChange}
                            placeholder={
                                props.placeholder
                                    ? props.placeholder
                                    : 'Enter ' + props.title
                            }
                            required={
                                props.required !== undefined
                                    ? props.required
                                    : false
                            }
                        />
                    )}
                    {props.type == 'select' && (
                        <Select
                            default={props.default}
                            error={props.columnError(props.name)}
                            id={inputId}
                            name={props.name}
                            onChangeCallback={onChange}
                            options={props.options}
                            placeholder={props.placeholder}
                            required={props.required}
                        />
                    )}
                </FormGroup>
            )}
            {props.hidden === true && (
                <input
                    type="hidden"
                    className="hide"
                    id={inputId}
                    name={props.name}
                    value={values[props.name]}
                />
            )}
        </>
    )
}

function FormGroups(props) {
    return (
        <>
            {props.columns.map((column) => {
                return (
                    <FormGroupItem
                        {...column}
                        key={'fgi-' + column.name}
                        changeCallback={props.changeCallback}
                        columnError={props.columnError}
                        values={props.values}
                    />
                )
            })}
        </>
    )
}
