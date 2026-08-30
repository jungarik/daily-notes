"""Contextmenu section — change a note's path, or bulk-rename a folder.

Self-contained vertical: endpoints.py → helper.py → store.py. Path validation is
duplicated here (over shared config + i18n). No imports from `services`/`stores`.
"""
