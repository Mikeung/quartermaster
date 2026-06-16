import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseScanner(ABC):
    """All scanners are read-only observers. They never modify targets."""

    name: str = "base"

    def run(self, target: str) -> dict[str, Any]:
        logger.info("Scanner starting", extra={"scanner": self.name, "target": target})
        result = self._scan(target)
        logger.info(
            "Scanner completed",
            extra={"scanner": self.name, "target": target, "keys": list(result.keys())},
        )
        return result

    @abstractmethod
    def _scan(self, target: str) -> dict[str, Any]: ...
