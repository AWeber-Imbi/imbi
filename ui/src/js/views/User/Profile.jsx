import { Link } from 'react-router-dom'
import PropTypes from 'prop-types'
import React, { Fragment, useContext, useEffect } from 'react'
import { useTranslation } from 'react-i18next'

import { Context } from '../../state'
import { User } from '../../schema'
import { Button } from '../../components'

function Groups({ groups }) {
  return (
    <Fragment>
      {groups.map((group) => {
        return (
          <Link
            className="inline-flex items-center px-2.5 py-0.5 mr-2 rounded-full text-xs font-medium bg-blue-700 text-white"
            key={group}
            to={'/ui/admin/groups#' + group}>
            {group}
          </Link>
        )
      })}
    </Fragment>
  )
}
Groups.defaultProps = {
  groups: []
}
Groups.propTypes = {
  groups: PropTypes.arrayOf(PropTypes.string)
}

const Item = ({ label, value, children }) => {
  return (
    <div className="px-4 py-2 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
      <dt className="text-sm font-medium text-gray-500">{label}</dt>
      <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2">
        {value !== undefined && value}
        {children !== undefined && children}
      </dd>
    </div>
  )
}
Item.propTypes = {
  label: PropTypes.string.isRequired,
  value: PropTypes.string,
  children: PropTypes.node
}

function Profile({ user }) {
  const [state, dispatch] = useContext(Context)
  const { t } = useTranslation()

  function redirectToGitlab(e) {
    e.preventDefault()
    document.location =
      `${state.metadata.gitlabDetails.authorizationEndpoint}` +
      `?client_id=${state.metadata.gitlabDetails.clientId}` +
      `&redirect_uri=${state.metadata.gitlabDetails.redirectURI}` +
      `&response_type=code` +
      `&state=${user.username}` +
      `&scope=api`
  }

  useEffect(() => {
    dispatch({
      type: 'SET_PAGE',
      payload: {
        title: t('user.profile.title', { displayName: user.display_name }),
        url: new URL('/ui/user/profile', state.baseURL.toString())
      }
    })
  }, [])
  return (
    <div className="container mx-auto my-auto max-w-4xl pb-0 bg-white shadow overflow-hidden sm:rounded-lg">
      <div className="px-4 py-5 sm:px-6">
        <h3 className="text-lg leading-6 font-medium text-gray-900">
          User Profile
        </h3>
      </div>
      <div className="bg-gray-50 border-t border-gray-200 py-5">
        <dl>
          <Item
            label={t('user.profile.displayName')}
            value={user.display_name}
          />
          <Item label={t('user.profile.userName')} value={user.username} />
          <Item label={t('user.profile.userType')} value={user.user_type} />
          {user.user_type !== 'internal' && (
            <Item
              label={t('user.profile.externalId')}
              value={user.external_id}
            />
          )}
          <Item
            label={t('user.profile.emailAddress')}
            value={user.email_address}
          />
          <Item label={t('user.profile.groups')}>
            <Groups groups={user.groups} />
          </Item>
          <Item
            label={t('user.profile.integrations')}
            value={user.integrations.join()}
          />
          {!user.integrations.includes('gitlab') && (
            <Button onClick={redirectToGitlab}>Connect to gitlab</Button>
          )}
        </dl>
      </div>
    </div>
  )
}

Profile.propTypes = {
  user: PropTypes.exact(User)
}

export { Profile }
