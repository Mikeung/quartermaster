"""On-box outbound connection evidence — parse, provider-tag, never raise."""

from __future__ import annotations

from datetime import UTC, datetime

from economics.connection_evidence import (
    Connection,
    collect_outbound_connections,
    connections_to_provider,
)

_NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)

# A realistic `ss -tnp state established` capture.
_SS = """\
Recv-Q Send-Q Local Address:Port Peer Address:Port Process
0      0      10.0.0.2:38744 160.79.104.10:443 users:(("python3.12",pid=4242,fd=7))
0      0      10.0.0.2:51020 104.18.32.47:443 users:(("node",pid=1337,fd=12))
0      0      10.0.0.2:22 203.0.113.9:49500 users:(("sshd",pid=999,fd=3))
"""


def _collect(ip_map):
    return collect_outbound_connections(now=_NOW, ss_output=_SS, ip_provider_map=ip_map)


class TestParse:
    def test_extracts_process_pid_remote(self):
        conns = _collect({})
        procs = {c.process: c for c in conns}
        assert procs["python3.12"].pid == 4242
        assert procs["python3.12"].remote_ip == "160.79.104.10"
        assert procs["python3.12"].remote_port == 443
        assert procs["python3.12"].observed_at == _NOW.isoformat()

    def test_garbage_never_raises(self):
        assert collect_outbound_connections(now=_NOW, ss_output="junk\n\n", ip_provider_map={}) == []


class TestProviderTagging:
    def test_tags_known_provider_ip(self):
        conns = _collect({"160.79.104.10": "anthropic"})
        anth = connections_to_provider("anthropic", conns)
        assert len(anth) == 1 and anth[0].process == "python3.12"

    def test_untagged_connection_has_none_provider(self):
        conns = _collect({"160.79.104.10": "anthropic"})
        node = next(c for c in conns if c.process == "node")
        assert node.provider is None

    def test_google_gemini_alias(self):
        conns = [Connection("p", 1, "1.2.3.4", 443, "google", _NOW.isoformat())]
        assert len(connections_to_provider("gemini", conns)) == 1
