"""
Project Related Request Handlers

"""
from tornado import web

from imbi import common
from . import (dependencies,
               dependency,
               inventory,
               link,
               links,
               options,
               project)

URLS = [
    web.url(r'^/project/$', project.RequestHandler),
    web.url(r'^/project/(?P<id>{})$'.format(common.UUID_PATTERN),
            project.RequestHandler, name='project'),
    web.url(r'^/project/(?P<project_id>{})/link'.format(common.UUID_PATTERN),
            link.RequestHandler),
    web.url(r'^/project/(?P<project_id>{})/link/'
            r'(?P<link_type>[\w_-]+)$'.format(common.UUID_PATTERN),
            link.RequestHandler, name='project-link'),
    web.url(r'^/project/(?P<project_id>{})/links'.format(common.UUID_PATTERN),
            links.RequestHandler, name='project-links'),
    web.url(r'^/project/(?P<project_id>{})/dependency'.format(
                common.UUID_PATTERN),
            dependency.RequestHandler),
    web.url(r'^/project/(?P<project_id>{})/dependency/'
            r'(?P<dependency_id>{})$'.format(
                common.UUID_PATTERN, common.UUID_PATTERN),
            dependency.RequestHandler, name='project-dependency'),
    web.url(r'^/project/(?P<project_id>{})/dependencies'.format(
                common.UUID_PATTERN),
            dependencies.RequestHandler, name='project-dependencies'),
    web.url(r'^/project/options$', options.RequestHandler,
            name='project-options'),
    web.url(r'^/projects/$', inventory.RequestHandler, name='projects')
]
