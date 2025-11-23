"""
Piccolo configuration for Imbi.

This file is required by Piccolo ORM for database configuration.
"""

from piccolo.conf.apps import AppRegistry

from imbi.database import DB

# Database instance
DB = DB

# App registry for migrations (not yet used)
APP_REGISTRY = AppRegistry(apps=["imbi.models"])
