"""Command registry behind ``manifest`` and ``describe``.

Discovery is inert: it never runs a backend, touches the game or reads user
data. Each route declares its group, action, effect, platform availability,
required configuration and the evidence a caller should keep. Availability is
a static claim; execution re-checks every requirement.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .errors import UNKNOWN_ROUTE, Failure

EFFECTS = (
    "inert",               # discovery only
    "writes-config",       # user configuration under the toolkit home
    "downloads-backends",  # pinned HTTPS downloads into the backends directory
    "writes-output",       # new output directory with artifacts and receipt
    "query-engine",        # reads fresh game state through the external console
    "changes-game",        # launches, loads, restarts or stops the game
    "captures-display",    # records or screenshots the game window
)

STATUS = ("available", "implemented", "planned", "deferred", "unsupported")
# available: native Windows receipt in docs/SUPPORT.md. implemented: code and offline
# tests exist; executes on Windows but has no native receipt yet. planned: contract only,
# work intended for this release. deferred: contract only, explicitly not in this release.


@dataclass
class Route:
    group: str
    action: str
    summary: str
    effect: str
    status: str = "available"
    owner: str = "core"
    requires_config: list[str] = field(default_factory=list)
    requires_windows: bool = False
    evidence: str = "Keep this invocation's stdout JSON and exit status."
    notes: str = ""

    @property
    def id(self) -> str:
        return f"{self.group}.{self.action}"

    def argv(self) -> list[str]:
        return ["pat", self.group, self.action]

    def to_dict(self) -> dict:
        row = asdict(self)
        row["id"] = self.id
        row["argv"] = self.argv()
        return row


_ROUTES: dict[str, Route] = {}


def register(route: Route) -> Route:
    if route.effect not in EFFECTS:
        raise ValueError(f"Unknown effect {route.effect!r} for {route.id}")
    if route.status not in STATUS:
        raise ValueError(f"Unknown status {route.status!r} for {route.id}")
    if route.id in _ROUTES:
        raise ValueError(f"Duplicate route {route.id}")
    _ROUTES[route.id] = route
    return route


def routes() -> list[Route]:
    return [_ROUTES[key] for key in sorted(_ROUTES)]


def find(group: str, action: str) -> Route:
    route = _ROUTES.get(f"{group}.{action}")
    if route is None:
        raise Failure(UNKNOWN_ROUTE, f"Unknown route {group} {action}",
                      "Run: pat manifest --json to list every route.")
    return route


def manifest(platform_info: dict) -> dict:
    rows = [r.to_dict() for r in routes()]
    for row in rows:
        if row["requires_windows"] and not platform_info.get("game_control_supported", platform_info.get("supported")):
            row["available_here"] = False
            row["availability_reason"] = "requires native Windows"
        else:
            row["available_here"] = row["status"] in ("available", "implemented")
            row["availability_reason"] = "" if row["available_here"] else row["status"]
    return {
        "platform": platform_info,
        "effects": list(EFFECTS),
        "statuses": list(STATUS),
        "routes": rows,
        "counts": {s: sum(1 for r in rows if r["status"] == s) for s in STATUS},
    }
