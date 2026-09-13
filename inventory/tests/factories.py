"""Shared fixture builders for the inventory test suite.

Kept deliberately small and explicit -- these mirror the real shapes the app
creates (a container holds drawers, a drawer holds bins, a Part is located by
zero or more StockItems), so tests read like the actual domain rather than
like ORM plumbing.
"""
from django.contrib.auth import get_user_model

from inventory.models import (
    Bin,
    BOMLine,
    BOMRevision,
    Category,
    Container,
    Drawer,
    Part,
    Project,
    StockItem,
)


def make_user(username="seth", password="test-pass-123", **kwargs):
    return get_user_model().objects.create_user(username=username, password=password, **kwargs)


def make_container(number=1, container_type="cabinets", name="", **kwargs):
    return Container.objects.create(number=number, container_type=container_type, name=name, **kwargs)


def make_drawer(container, label="drawer 1", **kwargs):
    return Drawer.objects.create(container=container, label=label, **kwargs)


def make_bin(drawer, bin_number=1, **kwargs):
    return Bin.objects.create(drawer=drawer, bin_number=bin_number, **kwargs)


def make_part(name="1.8 inch SPI TFT module", **kwargs):
    return Part.objects.create(name=name, **kwargs)


def make_category(name="Displays"):
    return Category.objects.create(name=name)


def make_stock(part, container, drawer=None, quantity=None, **kwargs):
    return StockItem.objects.create(part=part, container=container, drawer=drawer, quantity=quantity, **kwargs)


def make_project_with_bom(name="Blinky", lines=None, version=None):
    """lines: list of (part, quantity_required)."""
    project = Project.objects.create(name=name)
    revision = BOMRevision.objects.create(project=project, **({"version": version} if version else {}))
    for part, qty in (lines or []):
        BOMLine.objects.create(revision=revision, part=part, quantity_required=qty)
    return project, revision
