"""
backend/database/__init__.py

Database persistence, reliability, and backup subsystem for HINAKU.
"""

from .backup import (
    DatabaseBackupManager,
    DatabaseWriteCoordinator,
    DatabaseIntegrityError,
    DatabaseRestoreError,
    DatabaseRestoreFatalError,
    get_backup_manager,
    get_write_coordinator,
    coordinated_write,
)

__all__ = [
    "DatabaseBackupManager",
    "DatabaseWriteCoordinator",
    "DatabaseIntegrityError",
    "DatabaseRestoreError",
    "DatabaseRestoreFatalError",
    "get_backup_manager",
    "get_write_coordinator",
    "coordinated_write",
]
