#!/usr/bin/env python3
"""Env contract CLI.

Walks every ``services/*/env.contract.yaml``, lets the operator inspect
which environment variables each service declares, validate that the local
``docker compose`` stack supplies every required one, and emit a preview
k8s ``ConfigMap`` + ``Secret`` pair from a contract. Stand-in for the
future deploy portal until that UI ships.

Usage:
    deploy/tools/contracts.py list                  # tabella di tutti i contratti
    deploy/tools/contracts.py list --service rest-adapter
    deploy/tools/contracts.py validate              # vs docker compose config
    deploy/tools/contracts.py render-k8s rest-adapter
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "deploy" / "compose" / "docker-compose.yml"

# Where each service expects its env to be edited, in dev. The deploy portal
# will replace this with k8s ConfigMap / Secret paths at production time.
EDIT_PATH = {
    "camara-gateway":     "deploy/compose/docker-compose.yml (environment: block)",
    "positioning-engine": "deploy/compose/docker-compose.yml (environment: block)",
    "wifi-positioning":   "deploy/compose/docker-compose.yml (environment: block)",
    "placement-editor":   "deploy/compose/docker-compose.yml (environment: block)",
    "rest-adapter":       "services/rest-adapter/.env (real creds) - fallback: docker-compose.yml demo defaults",
    "positioning-demo":   "services/positioning-demo/public/env-config.js (gitignored; copy from .example.js)",
}

# Special edit-path for window.__ENV__ vars in placement-editor (Mapbox token).
ENV_CONFIG_PATH = {
    "placement-editor": "services/placement-editor/frontend/public/env-config.js (gitignored; copy from .example.js)",
    "positioning-demo": "services/positioning-demo/public/env-config.js (gitignored; copy from .example.js)",
}


@dataclass
class Var:
    name: str
    required: bool
    sensitive: bool
    default: str | None
    description: str
    runtime_layer: str | None
    example: str | None
    set_by: str | None = None      # compose | secret | operator
    consumed_by: list | None = None
    writable: bool = False         # path the service WRITES at runtime -> needs a PVC, not a read-only mount


@dataclass
class Contract:
    service: str
    description: str
    path: Path
    vars: list[Var]
    kind: str = "internal"             # ui | api | internal
    external_origin: str | None = None  # VAR name KELT routes a public origin to, or None


def load_contracts() -> list[Contract]:
    out: list[Contract] = []
    for path in sorted((REPO_ROOT / "services").glob("*/env.contract.yaml")):
        raw = yaml.safe_load(path.read_text())
        vars_: list[Var] = []
        for entry in raw.get("required") or []:
            vars_.append(
                Var(
                    name=entry["name"],
                    required=True,
                    sensitive=bool(entry.get("sensitive", False)),
                    default=None,
                    description=entry.get("description", ""),
                    runtime_layer=entry.get("runtime_layer"),
                    example=entry.get("example"),
                    set_by=entry.get("set_by"),
                    consumed_by=entry.get("consumed_by"),
                    writable=bool(entry.get("writable", False)),
                )
            )
        for entry in raw.get("optional") or []:
            vars_.append(
                Var(
                    name=entry["name"],
                    required=False,
                    sensitive=bool(entry.get("sensitive", False)),
                    default=str(entry.get("default", "")),
                    description=entry.get("description", ""),
                    runtime_layer=entry.get("runtime_layer"),
                    example=entry.get("example"),
                    set_by=entry.get("set_by"),
                    consumed_by=entry.get("consumed_by"),
                    writable=bool(entry.get("writable", False)),
                )
            )
        out.append(
            Contract(
                service=raw["service"],
                description=raw.get("description", ""),
                path=path,
                vars=vars_,
                kind=raw.get("kind", "internal"),
                external_origin=raw.get("external_origin"),
            )
        )
    return out


def filter_services(contracts: Iterable[Contract], selected: str | None) -> list[Contract]:
    if not selected:
        return list(contracts)
    matches = [c for c in contracts if c.service == selected]
    if not matches:
        names = ", ".join(c.service for c in contracts)
        sys.exit(f"no contract for service '{selected}'. Available: {names}")
    return matches


def cmd_list(args: argparse.Namespace) -> int:
    contracts = filter_services(load_contracts(), args.service)
    for c in contracts:
        print(f"\n=== {c.service} ===")
        print(f"  {c.description}")
        print(f"  contract: {c.path.relative_to(REPO_ROOT)}")
        print(f"  {'VAR':<28} {'REQ':<4} {'SECRET':<7} {'DEFAULT'}")
        print(f"  {'-' * 28} {'-' * 4} {'-' * 7} {'-' * 30}")
        for v in c.vars:
            req = "yes" if v.required else "no"
            sec = "yes" if v.sensitive else "no"
            default = "" if v.required else (v.default or "")
            print(f"  {v.name:<28} {req:<4} {sec:<7} {default}")
    return 0


def _compose_resolved_env() -> dict[str, dict[str, str]]:
    """Run ``docker compose config`` and return a {service: {var: value}}
    dict. This is the authoritative view of what each container will see
    when the operator runs ``make demo``."""
    if not COMPOSE_FILE.exists():
        sys.exit(f"compose file not found at {COMPOSE_FILE}")
    out = subprocess.run(
        [
            "docker", "compose",
            "-p", "5g-northbound",
            "--project-directory", str(REPO_ROOT),
            "-f", str(COMPOSE_FILE),
            "config", "--format", "json",
        ],
        check=True, capture_output=True, text=True,
    )
    cfg = json.loads(out.stdout)
    resolved: dict[str, dict[str, str]] = {}
    for svc, body in (cfg.get("services") or {}).items():
        env = body.get("environment") or {}
        # `environment` may be dict or list. compose config --format json
        # normalises to dict, but be defensive.
        if isinstance(env, list):
            env = dict(e.split("=", 1) for e in env if "=" in e)
        resolved[svc] = {k: str(v) for k, v in env.items() if v is not None}
    return resolved


def cmd_validate(args: argparse.Namespace) -> int:
    """Default view: only vars the OPERATOR has to provide - required + any
    sensitive optional (token, secret). Hide everything that has a working
    default. The point is to answer "what do I need to set to deploy this"
    without drowning the operator in scenery."""
    contracts = filter_services(load_contracts(), args.service)
    resolved = _compose_resolved_env()
    overall_ok = True
    print("env-check  ·  what you need to provide per service")
    print("           ·  (use --verbose to also see optional vars with defaults)")
    for c in contracts:
        compose_env = resolved.get(c.service, {})
        if c.service not in resolved:
            print(f"\n  ⚠  {c.service} - not in compose, skipped")
            continue

        # Surface only the rows that need operator attention.
        rows: list[str] = []
        for v in c.vars:
            relevant = v.required or v.sensitive
            if not relevant and not args.verbose:
                continue
            # Where does the var come from?
            if v.runtime_layer == "window.__ENV__":
                marker = "◦"
                where = "env-config.js"
                value = "(set in env-config.js)"
            else:
                present = v.name in compose_env
                if present:
                    marker = "✓"
                    where = "compose"
                    value = "***" if v.sensitive else compose_env[v.name]
                elif v.required:
                    marker = "✘"
                    where = "MISSING"
                    value = "set this in compose / k8s before deploy"
                    overall_ok = False
                else:
                    marker = "·"
                    where = "default"
                    value = v.default or ""
            tag = "required" if v.required else ("sensitive" if v.sensitive else "optional")
            rows.append(f"    {marker} {v.name:<26} {tag:<10} [{where}] {value}")

        if rows:
            print(f"\n  {c.service}")
            edit = EDIT_PATH.get(c.service)
            if edit:
                print(f"    edit here:  {edit}")
            env_cfg = ENV_CONFIG_PATH.get(c.service)
            if env_cfg and any(v.runtime_layer == "window.__ENV__" for v in c.vars):
                print(f"    browser:    {env_cfg}")
            for r in rows:
                print(r)

    print()
    if overall_ok:
        print("  All required vars satisfied.")
    else:
        print("  Set the ✘ rows above before deploying.")
    return 0 if overall_ok else 1


def _print_service_detail(c: Contract, compose_env: dict[str, str]) -> None:
    print(f"\n  --- {c.service} ---")
    for v in c.vars:
        if v.runtime_layer == "window.__ENV__":
            print(f"    ◦ {v.name}  (runtime via env-config.js)")
            continue
        present = v.name in compose_env
        if v.required and not present:
            print(f"    ✘ MISSING required: {v.name}")
        elif not present:
            print(f"    · {v.name}  (optional, default '{v.default}')")
        else:
            val = "***" if v.sensitive else compose_env[v.name]
            print(f"    ✓ {v.name} = {val}")


def cmd_render_k8s(args: argparse.Namespace) -> int:
    contracts = filter_services(load_contracts(), args.service)
    [c] = contracts  # filter_services exits if zero, single-service arg gives one
    cm_data: dict[str, str] = {}
    secret_data: dict[str, str] = {}
    for v in c.vars:
        if v.sensitive:
            secret_data[v.name] = "<FILL>"
        else:
            cm_data[v.name] = v.default if v.default is not None else "<FILL>"
    ns = args.namespace
    print(f"# Generated from {c.path.relative_to(REPO_ROOT)}")
    print(f"# Replace every <FILL> sentinel with a real value before apply.")
    print("---")
    print(yaml.safe_dump({
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": f"{c.service}-config", "namespace": ns},
        "data": cm_data,
    }, sort_keys=False), end="")
    if secret_data:
        print("---")
        print(yaml.safe_dump({
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": f"{c.service}-secrets", "namespace": ns},
            "type": "Opaque",
            "stringData": secret_data,
        }, sort_keys=False), end="")
    return 0


def _looks_like_committed_secret(default: str | None) -> bool:
    """A sensitive var should ship without a real value. Empty or an obvious
    placeholder is fine; anything else is a committed-secret smell."""
    if not default:
        return False
    return "change" not in default.lower() and "example" not in default.lower()


def cmd_lint(args: argparse.Namespace) -> int:
    """Static contract hygiene. Errors fail CI; warnings are advisory.

      ERROR  same var name, conflicting `sensitive` across services
      ERROR  sensitive var carries a real (non-placeholder) default
      WARN   api/ui service without external_origin (KELT can't route it)
      WARN   var without set_by (dashboard wizard hides/derives from it)
    """
    contracts = load_contracts()
    errors: list[str] = []
    warns: list[str] = []

    sensitivity_by_name: dict[str, set[bool]] = {}
    for c in contracts:
        for v in c.vars:
            sensitivity_by_name.setdefault(v.name, set()).add(v.sensitive)
            if v.sensitive and _looks_like_committed_secret(v.default):
                errors.append(f"{c.service}.{v.name}: sensitive var has a real default ('{v.default}') - use a placeholder")
            # set_by defaults to 'compose' (internal, hidden from the dashboard
            # wizard). Only operator-provided vars need it explicit - and a
            # sensitive var MUST say where its value comes from (secret|operator).
            if v.sensitive and v.set_by is None:
                warns.append(f"{c.service}.{v.name}: sensitive but no set_by (secret|operator)")
        if c.kind in ("api", "ui") and not c.external_origin:
            warns.append(f"{c.service}: kind={c.kind} but no external_origin (KELT reachability needs it)")

    for name, flags in sensitivity_by_name.items():
        if len(flags) > 1:
            errors.append(f"var '{name}': inconsistent `sensitive` across services {flags} - one name, one meaning")

    for w in warns:
        print(f"\033[33m⚠\033[0m  {w}")
    for e in errors:
        print(f"\033[31m✗\033[0m  {e}")
    if errors:
        print(f"\n\033[31m✗\033[0m contracts lint: {len(errors)} error(s), {len(warns)} warning(s)")
        return 1
    print(f"\n\033[32m✓\033[0m contracts lint: clean ({len(warns)} warning(s))")
    return 0


def cmd_sensitivity_manifest(args: argparse.Namespace) -> int:
    """Emit the machine-readable sensitivity manifest KELT consumes: every env
    var -> tier -> Secret/ConfigMap routing + provenance. CI and the dashboard
    both read this instead of re-deriving sensitivity by hand."""
    contracts = load_contracts()
    by_name: dict[str, dict] = {}
    for c in contracts:
        for v in c.vars:
            rec = by_name.setdefault(v.name, {
                "name": v.name,
                "sensitive": v.sensitive,
                "tier": "secret" if v.sensitive else "configmap",
                "routes_to": "Secret" if v.sensitive else "ConfigMap",
                "set_by": v.set_by or "compose",
                "writable": v.writable,
                "consumed_by": set(),
                "services": set(),
            })
            rec["writable"] = rec.get("writable", False) or v.writable
            rec["services"].add(c.service)
            for cb in (v.consumed_by or [c.service]):
                rec["consumed_by"].add(cb)

    manifest = {
        "generated_from": "services/*/env.contract.yaml",
        "tiers": {"configmap": "Tier-0 (committable config)", "secret": "Tier-1 (sensitive; never committed)"},
        "services": [
            {"service": c.service, "kind": c.kind, "external_origin": c.external_origin}
            for c in contracts
        ],
        "vars": sorted(
            (
                {**r, "consumed_by": sorted(r["consumed_by"]), "services": sorted(r["services"])}
                for r in by_name.values()
            ),
            key=lambda r: r["name"],
        ),
    }
    out_path = REPO_ROOT / "deploy" / "contracts" / "sensitivity-manifest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2) + "\n")
    secrets = [v["name"] for v in manifest["vars"] if v["sensitive"]]
    print(f"\033[32m✓\033[0m wrote {out_path.relative_to(REPO_ROOT)}")
    print(f"   {len(manifest['vars'])} vars · {len(secrets)} secret(s): {', '.join(secrets) or '(none)'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_lint = sub.add_parser("lint", help="Static contract hygiene (naming, sensitivity, external_origin)")
    p_lint.set_defaults(func=cmd_lint)

    p_sens = sub.add_parser("sensitivity-manifest", help="Emit deploy/contracts/sensitivity-manifest.json")
    p_sens.set_defaults(func=cmd_sensitivity_manifest)

    p_list = sub.add_parser("list", help="Print every var from every contract")
    p_list.add_argument("--service", help="Only show one service")
    p_list.set_defaults(func=cmd_list)

    p_val = sub.add_parser("validate", help="Validate compose env against contracts")
    p_val.add_argument("--service", help="Only validate one service")
    p_val.add_argument("--verbose", "-v", action="store_true", help="Show every var, not just issues")
    p_val.set_defaults(func=cmd_validate)

    p_k8s = sub.add_parser("render-k8s", help="Emit ConfigMap + Secret YAML preview")
    p_k8s.add_argument("service", help="Service name (must match a contract)")
    p_k8s.add_argument("--namespace", default="5g-northbound")
    p_k8s.set_defaults(func=cmd_render_k8s)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
