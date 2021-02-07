import DateTime from 'luxon/src/datetime'
import React, { Fragment, useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Backdrop, Button, Form, Icon, Modal, Table } from '../../components'
import { FetchContext } from '../../contexts'
import { httpDelete, httpGet, httpPost, setDocumentTitle } from '../../utils'

function Settings() {
  const { t } = useTranslation()
  const [errorMessage, setErrorMessage] = useState(null)
  const fetch = useContext(FetchContext)
  const [refresh, setRefresh] = useState(false)
  const [showBackdrop, setShowBackdrop] = useState(false)
  const [newAuthToken, setNewAuthToken] = useState(null)
  const [showTokenForm, setShowTokenForm] = useState(false)
  const [tokens, setTokens] = useState(null)

  function formatDate(value) {
    if (value === undefined) return ''
    const date = DateTime.fromISO(value)
    return date.toLocaleString()
  }

  function formatAge(value) {
    if (value === null) return t('user.settings.authenticationTokens.unused')
    return DateTime.fromISO(value).toRelative()
  }

  function deleteToken(value) {
    const url = new URL(fetch.baseURL)
    url.pathname = `/authentication-tokens/${value}`
    httpDelete(fetch.function, url).then(({ data, success }) => {
      if (success === true) {
        setRefresh(true)
      } else {
        setErrorMessage(data)
      }
    })
  }

  function generateToken(formValues) {
    setShowBackdrop(true)
    const url = new URL(fetch.baseURL)
    url.pathname = '/authentication-tokens'
    httpPost(fetch.function, url, { name: formValues.name }).then(
      ({ data, success }) => {
        if (success === true) {
          setShowTokenForm(false)
          setRefresh(true)
          setNewAuthToken(data.token)
          setShowBackdrop(false)
        } else {
          setShowBackdrop(false)
          setErrorMessage(data)
        }
      }
    )
  }

  useEffect(() => {
    if (tokens === null || refresh === true) {
      const url = new URL(fetch.baseURL)
      url.pathname = '/authentication-tokens'
      httpGet(
        fetch.function,
        url,
        (result) => {
          setRefresh(false)
          setTokens(result)
        },
        (error) => {
          setErrorMessage(error)
        }
      )
    }
  }, [refresh, tokens])

  setDocumentTitle(t('user.settings.title'))
  return (
    <Fragment>
      <Form.MultiSectionForm
        title={t('user.settings.title')}
        disabled={false}
        errorMessage={errorMessage}
        icon="fas user-cog"
        sideBarLinks={[
          {
            href: '#tokens',
            label: t('user.settings.authenticationTokens.title')
          }
        ]}>
        <Form.Section
          name="api"
          title={t('user.settings.authenticationTokens.title')}
          firstSection={true}>
          <Fragment>
            <div className="flex items-center justify-between mt-3">
              <div
                dangerouslySetInnerHTML={{
                  __html: t('user.settings.authenticationTokens.description', {
                    interpolation: { escapeValue: false }
                  })
                }}
              />
              <div>
                <Button
                  className="btn-green"
                  onClick={(event) => {
                    event.preventDefault()
                    setShowTokenForm(true)
                  }}>
                  <Fragment>
                    <Icon className="mr-3" icon="fas plus-circle" />
                    {t('user.settings.authenticationTokens.buttonText')}
                  </Fragment>
                </Button>
              </div>
            </div>
            <Table
              columns={[
                {
                  title: t('common.name'),
                  name: 'name',
                  type: 'text',
                  tableOptions: {
                    className: 'truncate',
                    headerClassName: 'w-4/12'
                  }
                },
                {
                  title: t('user.settings.authenticationTokens.createdAt'),
                  name: 'created_at',
                  type: 'text',
                  tableOptions: {
                    className: 'text-center truncate',
                    headerClassName: 'text-center w-2/12',
                    lookupFunction: formatDate
                  }
                },
                {
                  title: t('user.settings.authenticationTokens.expiresAt'),
                  name: 'expires_at',
                  type: 'text',
                  tableOptions: {
                    className: 'text-center truncate',
                    headerClassName: 'text-center w-2/12',
                    lookupFunction: formatDate
                  }
                },
                {
                  title: t('user.settings.authenticationTokens.lastUsedAt'),
                  name: 'last_used_at',
                  type: 'text',
                  tableOptions: {
                    className: 'text-center truncate',
                    headerClassName: 'text-center w-3/12',
                    lookupFunction: formatAge
                  }
                }
              ]}
              data={tokens !== null ? tokens : []}
              itemKey="token"
              onDeleteClick={deleteToken}
            />
            {showTokenForm && (
              <Form.ModalForm
                columns={[
                  {
                    title: t('common.name'),
                    name: 'name',
                    type: 'text',
                    tableOptions: {
                      className: 'truncate'
                    }
                  }
                ]}
                formType="edit"
                jsonSchema={{
                  $schema: 'http://json-schema.org/draft-07/schema#',
                  type: 'object',
                  properties: {
                    name: {
                      type: 'string',
                      minLength: 3
                    }
                  },
                  additionalProperties: false,
                  required: ['name']
                }}
                onClose={() => {
                  setShowTokenForm(false)
                }}
                onSubmit={generateToken}
                savingTitle={t('user.settings.authenticationTokens.generating')}
                title={t('user.settings.authenticationTokens.generate')}
                values={{ name: '' }}
              />
            )}
          </Fragment>
        </Form.Section>
      </Form.MultiSectionForm>
      {newAuthToken !== null && (
        <Modal
          title={t('user.settings.authenticationTokens.generated')}
          buttons={
            <Button
              className="btn-blue"
              onClick={(event) => {
                event.preventDefault()
                setNewAuthToken(null)
              }}>
              {t('common.done')}
            </Button>
          }>
          <Fragment>
            <div
              className="my-4 leading-8 text-gray-600 font-semibold"
              dangerouslySetInnerHTML={{
                __html: t(
                  'user.settings.authenticationTokens.generatedWarning',
                  {
                    interpolation: { escapeValue: false }
                  }
                )
              }}
            />
            <div className="mt-5 flex justify-center rounded-md shadow-sm">
              <div className="relative inline-flex focus-within:z-10">
                <input
                  className="focus:outline-none outline-none block rounded-none rounded-l-md sm:text-sm text-center border-gray-300"
                  id="new-token"
                  readOnly={true}
                  style={{ width: '24rem' }}
                  type="text"
                  value={newAuthToken}
                />
              </div>
              <button
                className="-ml-px focus:outline-none relative inline-flex items-center space-x-2 px-4 py-2 border border-gray-300 text-sm font-medium rounded-r-md text-gray-700 bg-gray-50 hover:bg-gray-100"
                onClick={(event) => {
                  event.preventDefault()
                  const newToken = document.getElementById('new-token')
                  newToken.select()
                  document.execCommand('copy')
                }}>
                <Icon icon="fas clipboard" />
              </button>
            </div>
          </Fragment>
        </Modal>
      )}
      {showBackdrop && newAuthToken === null && <Backdrop />}
    </Fragment>
  )
}
export { Settings }
