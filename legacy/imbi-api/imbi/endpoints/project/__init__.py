"""
Project Related Request Handlers

"""
from tornado import web

from . import dependency, link, project

URLS = [
    web.url(
        r'^/projects$', project.CollectionRequestHandler, name='projects'),
    web.url(
        r'^/projects/(?P<namespace>[\w_-]+)/(?P<name>[\w_-]+)$',
        project.RecordRequestHandler, name='project'),

    web.url(
        r'^/projects/(?P<namespace>[\w_-]+)/(?P<name>[\w_-]+)/dependencies$',
        dependency.CollectionRequestHandler, name='project-dependencies'),
    web.url(
        r'^/projects/(?P<namespace>[\w_-]+)/(?P<name>[\w_-]+)/dependencies/'
        r'(?P<dependency_namespace>[\w_-]+)/(?P<dependency_name>[\w_-]+)$',
        dependency.RecordRequestHandler, name='project-dependency'),
    web.url(
        r'^/projects/(?P<namespace>[\w_-]+)/(?P<name>[\w_-]+)/links$',
        link.CollectionRequestHandler, name='project-links'),
    web.url(
        r'^/projects/(?P<namespace>[\w_-]+)/(?P<name>[\w_-]+)/links'
        r'/(?P<link_type>[\w_-]+)$',
        link.RecordRequestHandler, name='project-link')
]
