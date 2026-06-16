"""
CLI for quartermaster.

Commands:
  health             Check service health
  projects           List registered projects
  register           Register a new project
  survivability      Show survivability summary
  pressure           Show ingestion pressure
  storage            Show storage overview
  retention          Preview retention plan (dry-run)
  report             Generate markdown report
  send-test          Send a test event to verify ingestion
  integration-check  Validate integration setup

Usage:
    python -m cli.main health --url http://localhost:8000
    python -m cli.main projects --url http://localhost:8000
    python -m cli.main survivability --url http://localhost:8000
    python -m cli.main send-test --url http://localhost:8000 --project my-app
    python -m cli.main integration-check --url http://localhost:8000 --project my-app

Requirements: requests or httpx installed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

_DEFAULT_URL = "http://localhost:8000"


# ---------------------------------------------------------------------------
# HTTP helper (no SDK import — standalone)
# ---------------------------------------------------------------------------

def _http_get(url: str, timeout: float = 10.0) -> tuple[int, Any]:
    try:
        import httpx  # type: ignore[import-untyped]
        r = httpx.get(url, timeout=timeout)
        return r.status_code, r.json() if r.status_code == 200 else r.text
    except ImportError:
        pass
    try:
        import urllib.error
        import urllib.request
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            import json as _json
            return resp.status, _json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, e.reason
    except Exception as exc:
        return 0, str(exc)


def _http_post(url: str, payload: dict[str, Any], timeout: float = 10.0) -> tuple[int, Any]:
    import json as _json
    body = _json.dumps(payload).encode()
    try:
        import httpx  # type: ignore[import-untyped]
        r = httpx.post(url, json=payload, timeout=timeout)
        return r.status_code, r.json() if r.status_code == 200 else r.text
    except ImportError:
        pass
    try:
        import urllib.error
        import urllib.request
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, _json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, e.reason
    except Exception as exc:
        return 0, str(exc)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _ok(msg: str) -> None:
    print(f"  [OK]  {msg}")


def _warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def _err(msg: str) -> None:
    print(f"  [ERR]  {msg}")


def _header(title: str) -> None:
    print(f"\n=== {title} ===")


def _json_block(data: Any, indent: int = 2) -> None:
    print(json.dumps(data, indent=indent))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_health(args: argparse.Namespace) -> int:
    _header("Health Check")
    status_code, data = _http_get(f"{args.url}/health")
    if status_code == 200:
        _ok(f"Service reachable — status: {data.get('status', 'unknown')}")
        if "version" in data:
            _ok(f"Version: {data['version']}")
        return 0
    else:
        _err(f"Health check failed — HTTP {status_code}")
        return 1


def cmd_projects(args: argparse.Namespace) -> int:
    _header("Registered Projects")
    status_code, data = _http_get(f"{args.url}/projects")
    if status_code != 200:
        _err(f"Failed to list projects — HTTP {status_code}")
        return 1

    projects = data if isinstance(data, list) else data.get("projects", [])
    if not projects:
        print("  No projects registered.")
        return 0

    for p in projects:
        pid = p.get("project_id", "unknown")
        name = p.get("name", "")
        archived = p.get("archived", False)
        ingestion = p.get("ingestion_enabled", True)
        status_label = "archived" if archived else ("active" if ingestion else "paused")
        print(f"  {pid:<30}  {name:<30}  [{status_label}]")
    return 0


def cmd_register(args: argparse.Namespace) -> int:
    _header(f"Register Project: {args.project_id}")
    payload = {
        "project_id": args.project_id,
        "name": args.name or args.project_id,
        "description": args.description or "",
        "retention_profile": args.retention_profile,
        "deployment_profile": args.deployment_profile,
    }
    if args.tags:
        payload["tags"] = [t.strip() for t in args.tags.split(",")]

    status_code, data = _http_post(f"{args.url}/projects", payload)
    if status_code == 200:
        _ok(f"Project '{args.project_id}' registered successfully")
        return 0
    elif status_code == 409:
        _warn(f"Project '{args.project_id}' already exists")
        return 0
    else:
        _err(f"Registration failed — HTTP {status_code}: {data}")
        return 1


def cmd_survivability(args: argparse.Namespace) -> int:
    if args.report:
        _header("Survivability Report (Markdown)")
        status_code, data = _http_get(f"{args.url}/projects/survivability/report")
        if status_code == 200:
            content = data.get("report", "") if isinstance(data, dict) else str(data)
            print(content)
        else:
            _err(f"Failed — HTTP {status_code}")
            return 1
    else:
        _header("Survivability Summary")
        status_code, data = _http_get(f"{args.url}/projects/survivability")
        if status_code != 200:
            _err(f"Failed — HTTP {status_code}")
            return 1

        overall = data.get("overall_status", "unknown")
        outlook = data.get("long_term_outlook", "unknown")
        status_icon = {"ok": "[OK]", "warning": "[WARN]", "critical": "[ERR]"}.get(overall, "[?]")
        print(f"\n  Status: {status_icon} {overall.upper()}")
        print(f"  Outlook: {outlook}")

        checks = data.get("checks", [])
        if checks:
            print("\n  Checks:")
            for c in checks:
                icon = "[OK]" if c.get("passed") else "[FAIL]"
                print(f"    {icon}  {c.get('name', '')} — {c.get('message', '')}")

        advisory = data.get("advisory", [])
        if advisory:
            print("\n  Advisory:")
            for a in advisory:
                print(f"    • {a}")
    return 0


def cmd_pressure(args: argparse.Namespace) -> int:
    _header("Ingestion Pressure")
    status_code, data = _http_get(f"{args.url}/projects/pressure")
    if status_code != 200:
        _err(f"Failed — HTTP {status_code}")
        return 1

    summary = data.get("summary") or data
    ok = summary.get("ok_count", 0)
    warn = summary.get("warning_count", 0)
    crit = summary.get("critical_count", 0)
    total = summary.get("total_projects_checked", 0)

    print(f"\n  Projects checked: {total}")
    _ok(f"OK: {ok}")
    if warn:
        _warn(f"Warning: {warn}")
    if crit:
        _err(f"Critical: {crit}")

    obs = summary.get("observations", [])
    if obs:
        print("\n  Observations:")
        for o in obs:
            print(f"    • {o}")
    return 0


def cmd_storage(args: argparse.Namespace) -> int:
    _header("Storage Overview")
    status_code, data = _http_get(f"{args.url}/projects/storage/overview")
    if status_code != 200:
        _err(f"Failed — HTTP {status_code}")
        return 1

    summary = data.get("summary") or data
    print(f"\n  Total snapshots:  {summary.get('total_snapshots', 0)}")
    print(f"  Total LLM events: {summary.get('total_llm_events', 0)}")

    profiles = summary.get("project_profiles", [])
    if profiles:
        print("\n  Project breakdown:")
        for p in profiles:
            pid = p.get("project_id", "unknown")
            snaps = p.get("snapshot_count", 0)
            events = p.get("llm_event_count", 0)
            snap_share = p.get("snapshot_share", 0) * 100
            print(f"    {pid:<30}  snaps: {snaps:>5}  events: {events:>7}  share: {snap_share:.1f}%")

    runaway = summary.get("runaway_projects", [])
    if runaway:
        _warn(f"Runaway projects detected: {', '.join(runaway)}")
    return 0


def cmd_retention(args: argparse.Namespace) -> int:
    _header("Retention Preview (dry-run)")
    status_code, data = _http_get(f"{args.url}/operations/retention")
    if status_code != 200:
        _err(f"Failed — HTTP {status_code}")
        return 1

    plan = data.get("plan") or data
    snap_deletable = plan.get("snapshot_deletable_count", 0)
    event_deletable = plan.get("event_deletable_count", 0)
    snap_keep = plan.get("snapshot_keep_count", 0)

    print(f"\n  Snapshots to delete: {snap_deletable}")
    print(f"  Snapshots to keep:   {snap_keep}")
    print(f"  LLM events to delete: {event_deletable}")

    if snap_deletable == 0 and event_deletable == 0:
        _ok("No retention action needed")
    else:
        _warn(f"Run retention with dry_run=false to delete {snap_deletable + event_deletable} records")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    report_map = {
        "provider": "/llm/report/provider",
        "workflow": "/llm/report/workflow",
        "latency": "/llm/report/latency",
        "tokens": "/llm/report/tokens",
        "errors": "/llm/report/errors",
    }
    path = report_map.get(args.kind)
    if not path:
        _err(f"Unknown report kind '{args.kind}'. Choose from: {', '.join(report_map)}")
        return 1

    _header(f"LLM Report: {args.kind}")
    status_code, data = _http_get(f"{args.url}{path}")
    if status_code == 200:
        content = data.get("report", "") if isinstance(data, dict) else str(data)
        print(content)
        return 0
    _err(f"Failed — HTTP {status_code}")
    return 1


def cmd_send_test(args: argparse.Namespace) -> int:
    _header(f"Ingestion Smoke Test — project: {args.project}")

    payload = {
        "provider": "test",
        "model": "test-model",
        "workflow": "cli/smoke-test",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "latency_ms": 100.0,
        "success": True,
        "request_kind": "completion",
        "project_id": args.project,
        "metadata": {"source": "cli-smoke-test"},
        "schema_version": "1.0",
    }

    t0 = time.monotonic()
    status_code, data = _http_post(f"{args.url}/llm/events", payload)
    elapsed_ms = (time.monotonic() - t0) * 1000

    if status_code == 200:
        _ok(f"Event accepted ({elapsed_ms:.0f}ms)")
        warnings = data.get("warnings", []) if isinstance(data, dict) else []
        for w in warnings:
            _warn(f"Server warning: {w}")
        return 0
    elif status_code == 422:
        reason = data.get("rejection_reason") if isinstance(data, dict) else str(data)
        _err(f"Event rejected: {reason}")
        return 1
    else:
        _err(f"Unexpected response — HTTP {status_code}: {data}")
        return 1


def cmd_integration_check(args: argparse.Namespace) -> int:
    """Run a local integration check against the service."""
    _header(f"Integration Check — {args.url}  project: {args.project}")

    from tools.integration_check import IntegrationChecker
    checker = IntegrationChecker(base_url=args.url, project_id=args.project)
    report = checker.run()

    if args.json:
        _json_block(report.to_dict())
        return 0 if report.ready else 1

    print(f"\n  Overall: {'READY' if report.ready else 'NOT READY'}")
    print(f"  Checks passed: {report.passed}/{report.total}")

    for item in report.items:
        icon = "[OK]" if item["passed"] else "[FAIL]"
        print(f"    {icon}  {item['name']}: {item['message']}")

    if report.warnings:
        print("\n  Warnings:")
        for w in report.warnings:
            print(f"    • {w}")

    return 0 if report.ready else 1


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qm",
        description="quartermaster CLI",
    )
    parser.add_argument("--url", default=_DEFAULT_URL, help="Base URL of the service")

    sub = parser.add_subparsers(dest="command", required=True)

    # health
    sub.add_parser("health", help="Check service health")

    # projects
    sub.add_parser("projects", help="List registered projects")

    # register
    reg = sub.add_parser("register", help="Register a new project")
    reg.add_argument("project_id", help="Project ID (lowercase, dashes allowed)")
    reg.add_argument("--name", help="Display name")
    reg.add_argument("--description", default="", help="Short description")
    reg.add_argument("--tags", default="", help="Comma-separated tags")
    reg.add_argument("--retention-profile", default="standard",
                     choices=["minimal", "standard", "extended"])
    reg.add_argument("--deployment-profile", default="standard",
                     choices=["minimal", "standard", "extended"])

    # survivability
    surv = sub.add_parser("survivability", help="Show survivability summary")
    surv.add_argument("--report", action="store_true", help="Show as markdown report")

    # pressure
    sub.add_parser("pressure", help="Show ingestion pressure")

    # storage
    sub.add_parser("storage", help="Show storage overview")

    # retention
    sub.add_parser("retention", help="Preview retention plan (always dry-run)")

    # report
    rep = sub.add_parser("report", help="Generate a markdown report")
    rep.add_argument("kind", choices=["provider", "workflow", "latency", "tokens", "errors"],
                     help="Report type")

    # send-test
    st = sub.add_parser("send-test", help="Send a test ingestion event")
    st.add_argument("--project", required=True, help="Project ID to tag the test event")

    # integration-check
    ic = sub.add_parser("integration-check", help="Validate integration setup")
    ic.add_argument("--project", required=True, help="Project ID to validate against")
    ic.add_argument("--json", action="store_true", help="Output JSON")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "health": cmd_health,
        "projects": cmd_projects,
        "register": cmd_register,
        "survivability": cmd_survivability,
        "pressure": cmd_pressure,
        "storage": cmd_storage,
        "retention": cmd_retention,
        "report": cmd_report,
        "send-test": cmd_send_test,
        "integration-check": cmd_integration_check,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
