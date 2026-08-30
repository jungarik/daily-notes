"""Notecard section — the attachment image proxy the carousel loads.

An <img> can't send the initData header, so a short-lived signed token in the
URL is the auth. Self-contained: endpoints.py → helper.py → store.py, over
shared infra (media_token, object storage). No `services`/`stores` domain imports.
"""
