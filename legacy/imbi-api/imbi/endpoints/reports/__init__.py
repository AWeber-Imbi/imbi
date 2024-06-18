"""
System Reports

"""
from tornado import web

from . import (component_usage, namespace_kpis, namespace_shs_history,
               system_shs_history)

URLS = [
    web.url(r'/reports/component-usage', component_usage.RequestHandler),
    web.url(r'/reports/namespace-kpis', namespace_kpis.RequestHandler),
    web.url(r'/reports/namespace-shs-history',
            namespace_shs_history.RequestHandler),
    web.url(r'/reports/system-shs-history', system_shs_history.RequestHandler),
]
