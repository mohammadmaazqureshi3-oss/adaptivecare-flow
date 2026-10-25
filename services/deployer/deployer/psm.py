"""From the pathway model (PIM) to an engine container configuration (PSM).

Model-driven engineering as in the course's modeling deck: the published pathway is the
platform-independent model; this function generates the platform-specific one, a
container definition with its own queue and its own database schema. Template-based
generation, so it is filed under Category 4, not 3 (plan Section 4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SAFE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


@dataclass(frozen=True)
class EngineConfig:
    name: str  # container and host name, e.g. engine-triage-v1
    image: str
    pathway: str
    version: int
    version_id: int
    queue: str  # engine.triage.v1
    schema: str  # engine_triage_v1
    env: dict[str, str] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    health_path: str = "/health"
    port: int = 8000


def engine_config(
    pathway: str, version: int, version_id: int, image: str, platform_env: dict[str, str]
) -> EngineConfig:
    """Generate the PSM. Only safe characters reach container, queue and schema names."""
    if not SAFE.match(pathway):
        raise ValueError(f"pathway id {pathway!r} cannot be used in container or schema names")
    schema = f"engine_{pathway}_v{version}"
    env = {
        **platform_env,
        "ENGINE_VERSION_ID": str(version_id),
        "ENGINE_SCHEMA": schema,
    }
    return EngineConfig(
        name=f"engine-{pathway.replace('_', '-')}-v{version}",
        image=image,
        pathway=pathway,
        version=version,
        version_id=version_id,
        queue=f"engine.{pathway}.v{version}",
        schema=schema,
        env=env,
        labels={
            "adaptivecare.role": "engine",
            "adaptivecare.pathway": pathway,
            "adaptivecare.version": str(version),
        },
    )
