"""Vendor device discovery flow.

Sits on top of `client.fetch_discover_page` and walks pagination if the
schema declares it. Returns a flat list of normalised entries the editor
can consume to populate / sync the room's anchors.

Generic by construction: the only vendor-specific bits live in the
schema (path, list_path, pagination rules, mapping). Adding a new vendor
to this flow is a JSON edit; the code does not change.
"""

import logging
from typing import Any, Optional

from .client import fetch_discover_page
from .mapper import get_path, to_discover_entry
from .schema import DiscoverFilter, Pagination, Schema

log = logging.getLogger(__name__)

# Hard cap on pages so a misbehaving vendor cannot trap us in an infinite
# loop. 100 pages at the schema's default 100 / page = 10k devices, more
# than any indoor RTLS will ever expose.
_MAX_PAGES = 100


def _extract_list(payload: Any, list_path: str) -> list:
    """Pull the device array out of one page. `list_path` is the dotted
    path to the array (`""` means the response itself is the array)."""
    if not list_path:
        return payload if isinstance(payload, list) else []
    found = get_path(payload, list_path)
    return found if isinstance(found, list) else []


def _entry_passes_filter(entry: Any, filt: Optional[DiscoverFilter]) -> bool:
    """True when the entry should be included in the discover output.
    The single supported rule today is `require_path`: skip when the
    named dotted path resolves to None on this entry.
    """
    if filt is None:
        return True
    if filt.require_path:
        if get_path(entry, filt.require_path) is None:
            return False
    return True


async def discover(schema: Schema) -> Optional[list[dict[str, Any]]]:
    """Walk the vendor's list endpoint, page by page, and return the
    accumulated normalised entries. None on a request failure (so the
    editor can show "vendor unreachable" instead of silently empty).

    Pagination semantics:
      - "none": one GET, accept whatever array comes back.
      - "page": 1-indexed pages, stop when the running total reaches the
        vendor's reported total or when a page returns an empty array.
    """
    if schema.discover is None:
        return []
    block = schema.discover
    pagination: Pagination = block.pagination

    if pagination.type == "none":
        body = await fetch_discover_page(schema, page=None)
        if body is None:
            return None
        items = _extract_list(body, block.list_path)
        filtered = [e for e in items if _entry_passes_filter(e, block.filter)]
        log.info(
            "discover: vendor=%s items_in_response=%d kept_after_filter=%d (list_path=%r)",
            schema.vendor, len(items), len(filtered), block.list_path,
        )
        out = _normalise(filtered, block.mapping)
        log.info(
            "discover: vendor=%s mapped=%d dropped_by_mapping=%d",
            schema.vendor, len(out), len(filtered) - len(out),
        )
        return out

    # Page-based pagination.
    out: list[dict[str, Any]] = []
    declared_total: Optional[int] = None
    pages_walked = 0
    for page in range(1, _MAX_PAGES + 1):
        body = await fetch_discover_page(schema, page=page)
        if body is None:
            return None if not out else out
        items = _extract_list(body, block.list_path)
        filtered = [e for e in items if _entry_passes_filter(e, block.filter)]
        pages_walked += 1
        log.info(
            "discover: vendor=%s page=%d items_in_page=%d kept_after_filter=%d (list_path=%r)",
            schema.vendor, page, len(items), len(filtered), block.list_path,
        )
        if not items:
            break
        for entry in filtered:
            mapped = to_discover_entry(block.mapping, entry)
            if mapped is not None:
                out.append(mapped)
        if declared_total is None:
            t = get_path(body, pagination.total_path)
            if isinstance(t, (int, float)):
                declared_total = int(t)
                log.info(
                    "discover: vendor=%s declared_total=%d",
                    schema.vendor, declared_total,
                )
        if declared_total is not None and len(out) >= declared_total:
            break
    else:
        log.warning(
            "vendor %s discover hit page cap %d; truncating",
            schema.vendor, _MAX_PAGES,
        )
    log.info(
        "discover: vendor=%s done, pages=%d mapped=%d",
        schema.vendor, pages_walked, len(out),
    )
    return out


def _normalise(items: list, mapping) -> list[dict[str, Any]]:
    """Bulk-apply the per-entry mapping. Entries that produce None
    (missing vendor_device_id) are silently dropped."""
    out: list[dict[str, Any]] = []
    for entry in items:
        mapped = to_discover_entry(mapping, entry)
        if mapped is not None:
            out.append(mapped)
    return out
