"""
System Reports

"""
from tornado import web

from . import namespace_shs_history, namespace_kpis, system_shs_history

URLS = [
    web.url(r'/reports/namespace-shs-history',
            namespace_shs_history.RequestHandler),
    web.url(r'/reports/namespace-kpis',
            namespace_kpis.RequestHandler),
    web.url(r'/reports/namespace-shs-history',
            system_shs_history.RequestHandler),

]
