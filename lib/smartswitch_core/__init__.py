"""Core scanning and extraction logic for SmartSwitch Explorer."""

from smartswitch_core.metadata import enrich_inventory
from smartswitch_core.scan import build_inventory, discover_backup_roots, find_backups

__all__ = ["build_inventory", "discover_backup_roots", "enrich_inventory", "find_backups"]
