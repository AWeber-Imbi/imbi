"""
System Reports

"""
from tornado import web

from . import namespace_kpis

URLS = [
    web.url(r'/reports/namespace-kpis', namespace_kpis.RequestHandler)
]
