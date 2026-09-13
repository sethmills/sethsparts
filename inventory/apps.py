"""App configuration.

There is deliberately no `ready()` doing database work here. Branding is applied by
`inventory.middleware.SiteTimezoneMiddleware` on the first request instead, because
Django warns (correctly) about database access during app loading — and during a
fresh clone's first `migrate` there is no database to read yet.
"""
from django.apps import AppConfig


class InventoryConfig(AppConfig):
    name = "inventory"
    verbose_name = "Inventory"
