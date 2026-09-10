"""Derive the vendor half of the env contract from the active schema.

The variables an operator must set are named by the schema, not by this image:
the service is generic and is bound to one vendor by the document it loads.
`env.contract.yaml` covers only the variables the binary itself reads.
"""

from typing import Optional

from .schema import (
    AuthBasic,
    AuthBearer,
    AuthHeader,
    DiscoverMapping,
    Mapping,
    Schema,
)

# (declared_at, env name, sensitive, type)
_Site = tuple[str, str, bool, str]


def _sites(schema: Schema) -> list[_Site]:
    """Every EnvRef the schema carries, in declaration order.

    Sensitivity is positional: a credential is the auth password, token or
    header value. A path variable and a basic-auth username are not secrets.
    """
    out: list[_Site] = [("base_url", schema.base_url.env, False, "url")]
    for name, ref in schema.path_vars.items():
        out.append((f"path_vars.{name}", ref.env, False, "string"))
    auth = schema.auth
    if isinstance(auth, AuthBasic):
        out.append(("auth.username", auth.username.env, False, "string"))
        out.append(("auth.password", auth.password.env, True, "string"))
    elif isinstance(auth, AuthBearer):
        out.append(("auth.token", auth.token.env, True, "string"))
    elif isinstance(auth, AuthHeader):
        out.append(("auth.value", auth.value.env, True, "string"))
    if schema.discover is not None:
        for name, ref in schema.discover.path_vars.items():
            out.append((f"discover.path_vars.{name}", ref.env, False, "string"))
    if schema.diagnostics is not None:
        for i, fetch in enumerate(schema.diagnostics.on_demand):
            for name, ref in fetch.path_vars.items():
                out.append(
                    (
                        f"diagnostics.on_demand[{i}].path_vars.{name}",
                        ref.env,
                        False,
                        "string",
                    )
                )
    return out


def vendor_env(schema: Optional[Schema]) -> list[dict]:
    """Env entries the active schema requires, deduplicated by variable name.

    Every entry is required: a schema declares only the endpoints it uses, so a
    declared discover block means its variables are wanted. `sensitive` is the
    OR across the sites a name appears at. Entries carry no value; the adapter
    holds none.
    """
    if schema is None:
        return []
    by_name: dict[str, dict] = {}
    for declared_at, name, sensitive, type_ in _sites(schema):
        entry = by_name.setdefault(
            name, {"name": name, "sensitive": False, "type": type_, "declared_at": []}
        )
        entry["sensitive"] = entry["sensitive"] or sensitive
        entry["declared_at"].append(declared_at)
    return [by_name[name] for name in sorted(by_name)]


def _coverage(model: type, mapping) -> dict:
    supported = list(model.model_fields)
    mapped = set(mapping.model_dump(exclude_none=True))
    return {
        "supported": supported,
        "mapped": [f for f in supported if f in mapped],
        "unmapped": [f for f in supported if f not in mapped],
    }


def mapping_coverage(schema: Schema) -> dict:
    """Which measurement mapping fields this binary supports, and which the
    active document maps. An operator whose schema predates a field reads it
    under `unmapped` instead of losing the feature silently."""
    return _coverage(Mapping, schema.mapping)


def discover_mapping_coverage(schema: Schema) -> Optional[dict]:
    if schema.discover is None:
        return None
    return _coverage(DiscoverMapping, schema.discover.mapping)
