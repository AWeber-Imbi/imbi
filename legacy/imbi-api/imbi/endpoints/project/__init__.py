"""
Project Related Request Handlers

"""
from tornado import web

from imbi import constants
from . import dependencies, dependency,  inventory, link, links, project

URLS = [
    web.url(r'^/project/$', project.RequestHandler),
    web.url(
        r'^/project/(?P<id>{})$'.format(constants.UUID_PATTERN),
        project.RequestHandler, name='project'),
    web.url(
        r'^/project/(?P<project_id>{})/link'.format(constants.UUID_PATTERN),
        link.RequestHandler),
    web.url(
        r'^/project/(?P<project_id>{})/link/(?P<link_type>[\w_-]+)$'.format(
            constants.UUID_PATTERN),
        link.RequestHandler, name='project-link'),
    web.url(
        r'^/project/(?P<project_id>{})/links'.format(constants.UUID_PATTERN),
        links.RequestHandler, name='project-links'),
    web.url(
        r'^/project/(?P<project_id>{})/dependency'.format(
            constants.UUID_PATTERN),
        dependency.RequestHandler),
    web.url(
        r'^/project/(?P<project_id>{})/dependency/'
        r'(?P<dependency_id>{})$'.format(
            constants.UUID_PATTERN, constants.UUID_PATTERN),
        dependency.RequestHandler, name='project-dependency'),
    web.url(
        r'^/project/(?P<project_id>{})/dependencies'.format(
            constants.UUID_PATTERN),
        dependencies.RequestHandler, name='project-dependencies'),
    web.url(r'^/projects/$', inventory.RequestHandler, name='projects')
]
