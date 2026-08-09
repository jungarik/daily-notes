"""Persistence layer: thin data-access modules over the database.

Stores never import services or clients — layering is one-way
(clients → services → stores → db/config).
"""
