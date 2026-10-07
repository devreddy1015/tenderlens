"""Page parsers, one module per portal software.

DETAIL_PARSERS maps Source.kind to the parser module for it. Each module provides
parse_detail(html) -> dict of raw strings for ingest.validation, and raises
gepnic.NotADetailPage (or a subclass) for pages that are not tender details so the loader
quarantines them. Modules, not functions, are registered so the lookup happens at call time.
"""

from ingest.parsers import gepnic

DETAIL_PARSERS = {"gepnic": gepnic}
