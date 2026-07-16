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
from .mapper import classify_entry, get_path, to_discover_entry
from .schema import Classify, DiscoverFilter, Pagination, Schema

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


async def _walk_pages(schema: Schema) -> Optional[list[Any]]:
    """Walk the vendor's list endpoint and return the accumulated RAW records
    (one dict per device, exactly as the vendor sent them). None on a request
    failure. This is the single fetch+pagination walker; both the normalised
    `discover()` and the raw builder feed served by the router sit on top of it.

    Pagination semantics:
      - "none": one GET, accept whatever array comes back.
      - "page": 1-indexed pages, stop when the running total reaches the
        vendor's reported total or when a page returns an empty array.
    """
    block = schema.discover
    pagination: Pagination = block.pagination

    if pagination.type == "none":
        body = await fetch_discover_page(schema, page=None)
        if body is None:
            return None
        items = _extract_list(body, block.list_path)
        log.info(
            "discover: vendor=%s items_in_response=%d (list_path=%r)",
            schema.vendor, len(items), block.list_path,
        )
        return items

    raw: list[Any] = []
    declared_total: Optional[int] = None
    for page in range(1, _MAX_PAGES + 1):
        body = await fetch_discover_page(schema, page=page)
        if body is None:
            return None if not raw else raw
        items = _extract_list(body, block.list_path)
        log.info(
            "discover: vendor=%s page=%d items_in_page=%d (list_path=%r)",
            schema.vendor, page, len(items), block.list_path,
        )
        if not items:
            break
        raw.extend(items)
        if declared_total is None:
            t = get_path(body, pagination.total_path)
            if isinstance(t, (int, float)):
                declared_total = int(t)
                log.info("discover: vendor=%s declared_total=%d", schema.vendor, declared_total)
        if declared_total is not None and len(raw) >= declared_total:
            break
    else:
        log.warning("vendor %s discover hit page cap %d; truncating", schema.vendor, _MAX_PAGES)
    return raw


async def discover_raw(schema: Schema) -> Optional[list[Any]]:
    """The vendor's device list as RAW records - no mapping, no filter, no
    classify. Feeds the guided schema builder: the operator sees the vendor's
    actual field names to choose paths against. None on request failure."""
    if schema.discover is None:
        return []
    return await _walk_pages(schema)


async def discover(
    schema: Schema, *, apply_filter: bool = True
) -> Optional[list[dict[str, Any]]]:
    """Walk the vendor's list endpoint and return the accumulated NORMALISED
    entries. None on a request failure (so the editor can show "vendor
    unreachable" instead of silently empty).

    `apply_filter=True` (editor sync) keeps only entries passing the schema's
    include filter (anchors). `apply_filter=False` (asset onboarding via
    /devices) reads the list UNFILTERED - onboarding wants the tags the anchor
    filter drops. Either way, when the schema declares a `classify` block, each
    entry gains a `role` + `source_class` derived from the raw record.
    """
    if schema.discover is None:
        return []
    block = schema.discover
    raw = await _walk_pages(schema)
    if raw is None:
        return None
    filt = block.filter if apply_filter else None
    filtered = [e for e in raw if _entry_passes_filter(e, filt)]
    out = _normalise(filtered, block.mapping, block.classify)
    log.info(
        "discover: vendor=%s raw=%d kept_after_filter=%d mapped=%d",
        schema.vendor, len(raw), len(filtered), len(out),
    )
    return out


def _normalise(
    items: list, mapping, classify: Optional[Classify] = None
) -> list[dict[str, Any]]:
    """Bulk-apply the per-entry mapping. Entries that produce None
    (missing vendor_device_id) are silently dropped. When a `classify` block is
    present, merge the derived `role` + `source_class` (evaluated on the raw
    record, so structural predicates see the vendor's own fields)."""
    out: list[dict[str, Any]] = []
    for entry in items:
        mapped = to_discover_entry(mapping, entry)
        if mapped is not None:
            if classify is not None:
                mapped.update(classify_entry(classify, entry))
            out.append(mapped)
    return out
