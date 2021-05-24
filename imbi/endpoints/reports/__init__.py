"""
System Reports

"""
from tornado import web

from . import namespace_kpi_history, namespace_kpis

URLS = [
    web.url(r'/reports/namespace-kpi-history',
            namespace_kpi_history.RequestHandler),
    web.url(r'/reports/namespace-kpis',
            namespace_kpis.RequestHandler)
]
