import React, { useContext, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import {
    Button,
    Form,
    FormGroup,
    Input,
    Label,
    Modal,
    ModalHeader,
    ModalBody,
    ModalFooter,
} from 'reactstrap'

import { Alert, NavBar } from '../components'
import { FetchContext, SettingsContext, UserContext } from '../contexts'
import { getErrorMessage, httpPost } from '../utils'

export default function (props) {
    const { t } = useTranslation()
    const currentUser = useContext(UserContext)
    const fetch = useContext(FetchContext)
    const settings = useContext(SettingsContext)

    const [credentials, setCredentials] = useState({
        username: currentUser.username,
        password: null,
    })
    const [errorMessage, setErrorMessage] = useState(undefined)
    const [submitting, setSubmitting] = useState(false)

    const usernameRef = useRef()

    function onChange(e) {
        const { name, value } = e.target
        setCredentials({ ...credentials, [name]: value })
    }

    async function onSubmit(e) {
        e.preventDefault()
        setSubmitting(true)
        const response = await httpPost(
            fetch,
            '/ui/login',
            {
                username: credentials.username,
                password: credentials.password,
            },
            { credentials: 'include' }
        )
        if (response.success === true) {
            props.updateUser(response.data)
        } else {
            setErrorMessage(response.data)
            setSubmitting(false)
            usernameRef.current.focus()
        }
    }

    return (
        <>
            {currentUser.username === null && (
                <>
                    <NavBar />
                    <div className="main login">
                        <Modal
                            autoFocus
                            isOpen
                            fade={false}
                            backdrop={false}
                            centered
                        >
                            <form onSubmit={onSubmit}>
                                <ModalHeader>
                                    {settings.service_name} {t('common.login')}{' '}
                                </ModalHeader>
                                <ModalBody>
                                    <Alert color="danger" noClose>
                                        {errorMessage}
                                    </Alert>
                                    <FormGroup>
                                        <Label for="username">
                                            {t('common.username')}
                                        </Label>
                                        <input
                                            autoFocus
                                            className="form-control"
                                            name="username"
                                            autoComplete="username"
                                            ref={usernameRef}
                                            onChange={onChange}
                                            placeholder={
                                                (settings.ldap_enabled
                                                    ? 'LDAP '
                                                    : '') + 'Username'
                                            }
                                            type="text"
                                            value={
                                                credentials.username !== null
                                                    ? credentials.username
                                                    : ''
                                            }
                                        />
                                    </FormGroup>
                                    <FormGroup>
                                        <Label for="password">
                                            {t('common.password')}
                                        </Label>
                                        <Input
                                            name="password"
                                            autoComplete="current-password"
                                            onChange={onChange}
                                            placeholder="Password"
                                            type="password"
                                            value={
                                                credentials.password !== null
                                                    ? credentials.password
                                                    : ''
                                            }
                                        />
                                    </FormGroup>
                                </ModalBody>
                                <ModalFooter>
                                    <Button
                                        type="submit"
                                        color="primary"
                                        disabled={
                                            submitting ||
                                            credentials.username === null ||
                                            credentials.password === null
                                        }
                                    >
                                        <span className="fas fa-sign-in-alt"></span>
                                        {t('common.login')}
                                    </Button>
                                </ModalFooter>
                            </form>
                        </Modal>
                    </div>
                </>
            )}
        </>
    )
}
