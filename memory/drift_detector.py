import logging
from typing import Any

logger = logging.getLogger(__name__)

# Ports above this threshold are candidates for ephemeral classification.
# Justified by C7: ports 25492/27099/36891/45966 generated 4 false drift events
# across 2 consecutive snapshots with no operational relevance (localhost-only,
# no stable process attribution, correlated with OOM-killed dev-tool process).
_EPHEMERAL_PORT_THRESHOLD = 20000

# Known dev-tool processes that bind ephemeral localhost ports.
_DEV_TOOL_PROCESSES = frozenset({"node", "code", "electron"})


def _is_ephemeral_port(port: int, ports_raw: list[dict]) -> bool:
    """Return True if port qualifies as a telemetry-only ephemeral event.

    Classifies as ephemeral ONLY when all three hold:
    1. Port number >= _EPHEMERAL_PORT_THRESHOLD (high ephemeral range)
    2. localhost_only = True (no external exposure)
    3. Empty process attribution OR process is a known dev-tool

    Conservative: ports missing from ports_raw metadata are treated as
    operational (unknown = potentially significant).
    """
    if port < _EPHEMERAL_PORT_THRESHOLD:
        return False
    for p in ports_raw:
        if p.get("port") == port:
            if not p.get("localhost_only", False):
                return False
            process = p.get("process", "")
            if not process:
                return True
            return any(d in process for d in _DEV_TOOL_PROCESSES)
    return False  # port absent from metadata — conservative: treat as operational


class VpsDriftDetector:
    """Compares two VPS state snapshots and reports infrastructure-level changes.

    Operates on the output of scanners.vps_scanner.collect_vps_state().
    Detects new/removed services, ports, containers, and domains.
    Advisory only. No autonomous action.
    """

    def compare(self, previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
        changes: list[dict[str, Any]] = []
        human_readable: list[str] = []
        telemetry_events: list[str] = []

        prev_services = set(previous.get("service_names", []))
        curr_services = set(current.get("service_names", []))
        for s in sorted(curr_services - prev_services):
            changes.append({"type": "NEW_SERVICE", "value": s})
            human_readable.append(f"New systemd service: {s}")
        for s in sorted(prev_services - curr_services):
            changes.append({"type": "REMOVED_SERVICE", "value": s})
            human_readable.append(f"Systemd service removed: {s}")

        prev_ports = set(previous.get("port_set", []))
        curr_ports = set(current.get("port_set", []))
        prev_ports_raw = previous.get("ports_raw", [])
        curr_ports_raw = current.get("ports_raw", [])

        for p in sorted(curr_ports - prev_ports):
            classification = (
                "telemetry_only" if _is_ephemeral_port(p, curr_ports_raw) else "operational"
            )
            changes.append({"type": "NEW_PORT", "value": p, "classification": classification})
            if classification == "operational":
                human_readable.append(f"New listening port: {p}")
            else:
                telemetry_events.append(f"Ephemeral port appeared: {p} (localhost dev-tool)")

        for p in sorted(prev_ports - curr_ports):
            classification = (
                "telemetry_only" if _is_ephemeral_port(p, prev_ports_raw) else "operational"
            )
            changes.append({"type": "REMOVED_PORT", "value": p, "classification": classification})
            if classification == "operational":
                human_readable.append(f"Port no longer listening: {p}")
            else:
                telemetry_events.append(f"Ephemeral port closed: {p} (localhost dev-tool)")

        prev_containers = set(previous.get("container_names", []))
        curr_containers = set(current.get("container_names", []))
        for c in sorted(curr_containers - prev_containers):
            changes.append({"type": "NEW_CONTAINER", "value": c})
            human_readable.append(f"New Docker container: {c}")
        for c in sorted(prev_containers - curr_containers):
            changes.append({"type": "REMOVED_CONTAINER", "value": c})
            human_readable.append(f"Docker container gone: {c}")

        prev_domains = set(previous.get("domain_names", []))
        curr_domains = set(current.get("domain_names", []))
        for d in sorted(curr_domains - prev_domains):
            changes.append({"type": "NEW_DOMAIN", "value": d})
            human_readable.append(f"New nginx domain: {d}")
        for d in sorted(prev_domains - curr_domains):
            changes.append({"type": "REMOVED_DOMAIN", "value": d})
            human_readable.append(f"Nginx domain removed: {d}")

        prev_unscanned = set(previous.get("unscanned_services", []))
        curr_unscanned = set(current.get("unscanned_services", []))
        for s in sorted(curr_unscanned - prev_unscanned):
            changes.append({"type": "NEW_UNSCANNED_SERVICE", "value": s})
            human_readable.append(f"New service without scan coverage: {s}")

        # operational_count: events where classification is "operational" or not set
        operational_count = sum(
            1 for c in changes if c.get("classification", "operational") == "operational"
        )
        telemetry_count = len(changes) - operational_count

        if operational_count > 0:
            summary = f"Detected {operational_count} VPS infrastructure change(s)"
            if telemetry_count:
                summary += f" ({telemetry_count} ephemeral port event(s) as telemetry-only)"
        elif telemetry_count:
            summary = (
                f"No operational drift detected "
                f"({telemetry_count} ephemeral port event(s) classified as telemetry-only)"
            )
        else:
            summary = "No significant infrastructure drift detected."

        logger.info(
            "VPS drift comparison complete",
            extra={"operational_count": operational_count, "telemetry_count": telemetry_count},
        )
        return {
            "change_count": operational_count,
            "telemetry_count": telemetry_count,
            "changes": changes,
            "summary": summary,
            "human_readable": human_readable,
            "telemetry_events": telemetry_events,
        }


class DriftDetector:
    """Compares two operational snapshot payloads and produces a structured drift report.

    Deterministic, evidence-based, rule-driven. No AI reasoning.
    Advisory output only.
    """

    def compare(self, previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
        changes: list[dict[str, Any]] = []
        human_readable: list[str] = []

        self._compare_llm_detections(
            previous.get("llm_detections", []),
            current.get("llm_detections", []),
            changes,
            human_readable,
        )

        prev_repo = previous.get("scanner_results", {}).get("results", {}).get("repo_scanner", {})
        curr_repo = current.get("scanner_results", {}).get("results", {}).get("repo_scanner", {})

        if prev_repo and curr_repo:
            self._compare_repo(prev_repo, curr_repo, changes, human_readable)

        logger.info(
            "Drift comparison complete",
            extra={"change_count": len(changes), "changes": [c["type"] for c in changes]},
        )

        return {
            "change_count": len(changes),
            "changes": changes,
            "summary": (
                f"Detected {len(changes)} operational change(s)"
                if changes
                else "No changes detected"
            ),
            "human_readable": human_readable,
        }

    def _compare_llm_detections(
        self,
        prev: list[dict[str, Any]],
        curr: list[dict[str, Any]],
        changes: list[dict[str, Any]],
        human_readable: list[str],
    ) -> None:
        prev_providers = {d["provider"] for d in prev}
        curr_providers = {d["provider"] for d in curr}

        for provider in curr_providers - prev_providers:
            changes.append({"type": "llm_provider_added", "value": provider})
            human_readable.append(f"New LLM provider detected in source code: {provider}")

        for provider in prev_providers - curr_providers:
            changes.append({"type": "llm_provider_removed", "value": provider})
            human_readable.append(f"LLM provider no longer detected: {provider}")

    def _compare_repo(
        self,
        prev: dict[str, Any],
        curr: dict[str, Any],
        changes: list[dict[str, Any]],
        human_readable: list[str],
    ) -> None:
        # LLM SDKs in package manifests
        for sdk in set(curr.get("llm_sdks", [])) - set(prev.get("llm_sdks", [])):
            changes.append({"type": "llm_sdk_added", "value": sdk})
            human_readable.append(f"New LLM SDK added to packages: {sdk}")

        for sdk in set(prev.get("llm_sdks", [])) - set(curr.get("llm_sdks", [])):
            changes.append({"type": "llm_sdk_removed", "value": sdk})
            human_readable.append(f"LLM SDK removed from packages: {sdk}")

        # Frameworks
        for fw in set(curr.get("frameworks", [])) - set(prev.get("frameworks", [])):
            changes.append({"type": "framework_added", "value": fw})
            human_readable.append(f"New framework detected: {fw}")

        for fw in set(prev.get("frameworks", [])) - set(curr.get("frameworks", [])):
            changes.append({"type": "framework_removed", "value": fw})
            human_readable.append(f"Framework no longer detected: {fw}")

        # Docker
        prev_docker = prev.get("docker", {}).get("present", False)
        curr_docker = curr.get("docker", {}).get("present", False)
        if not prev_docker and curr_docker:
            changes.append({"type": "docker_added"})
            human_readable.append("Docker configuration added to project")
        elif prev_docker and not curr_docker:
            changes.append({"type": "docker_removed"})
            human_readable.append("Docker configuration removed from project")

        # CI/CD
        for ci in set(curr.get("ci_cd", [])) - set(prev.get("ci_cd", [])):
            changes.append({"type": "ci_added", "value": ci})
            human_readable.append(f"New CI/CD system detected: {ci}")

        for ci in set(prev.get("ci_cd", [])) - set(curr.get("ci_cd", [])):
            changes.append({"type": "ci_removed", "value": ci})
            human_readable.append(f"CI/CD system no longer detected: {ci}")

        # Primary language change
        prev_lang = prev.get("primary_language")
        curr_lang = curr.get("primary_language")
        if prev_lang and curr_lang and prev_lang != curr_lang:
            changes.append({"type": "language_changed", "from": prev_lang, "to": curr_lang})
            human_readable.append(f"Primary language changed: {prev_lang} → {curr_lang}")

        # Significant file count change (>20%)
        prev_files = prev.get("total_files", 0)
        curr_files = curr.get("total_files", 0)
        if prev_files > 0:
            change_pct = abs(curr_files - prev_files) / prev_files
            if change_pct > 0.20:
                direction = "increased" if curr_files > prev_files else "decreased"
                changes.append(
                    {
                        "type": "file_count_changed",
                        "from": prev_files,
                        "to": curr_files,
                        "change_pct": round(change_pct * 100, 1),
                    }
                )
                human_readable.append(
                    f"File count {direction} significantly: "
                    f"{prev_files} → {curr_files} ({change_pct:.0%})"
                )
