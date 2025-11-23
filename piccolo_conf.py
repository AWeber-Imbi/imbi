"""
Piccolo configuration for Imbi.

This file is required by Piccolo ORM for database configuration.
"""

from piccolo.conf.apps import AppRegistry

from imbi.database import DB

# Database instance (imported for Piccolo to find)
DB = DB

# App registry for migrations (empty for now - will add when implementing migrations)
APP_REGISTRY = AppRegistry(apps=[])
