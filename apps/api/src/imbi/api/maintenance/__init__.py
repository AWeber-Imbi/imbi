"""Global maintenance operations (admin Maintenance page)."""

from imbi_api.maintenance.registry import (
    OPERATIONS,
    MaintenanceSlug,
    OperationDefinition,
)

__all__ = ['OPERATIONS', 'MaintenanceSlug', 'OperationDefinition']
