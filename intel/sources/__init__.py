"""Historical-award sources. Every module in this package defines one or more adapters
decorated with @register (intel.sources.base); importing the package discovers them all, so
adding a source never means editing a shared list."""

import importlib
import pkgutil

from intel.sources.base import REGISTRY, AwardRow, ImportContext, Source, register

for _module in pkgutil.iter_modules(__path__):
    if _module.name != "base":
        importlib.import_module(f"{__name__}.{_module.name}")

__all__ = ["REGISTRY", "AwardRow", "ImportContext", "Source", "register"]
