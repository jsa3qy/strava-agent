"""
Reusable query modules for Strava activity analysis.

This package contains modules created by the agent for commonly-used
query patterns. Each module is registered in registry.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

MODULES_DIR = Path(__file__).parent
REGISTRY_PATH = MODULES_DIR / "registry.json"


def get_registry():
    """Load the module registry."""
    with open(REGISTRY_PATH, "r") as f:
        return json.load(f)


def update_registry(name: str, file: str, description: str, functions: list[str]):
    """Add or update a module in the registry."""
    registry = get_registry()

    # Check if module already exists
    for module in registry["modules"]:
        if module["name"] == name:
            module["file"] = file
            module["description"] = description
            module["functions"] = functions
            break
    else:
        registry["modules"].append({
            "name": name,
            "file": file,
            "description": description,
            "functions": functions,
        })

    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)


def list_modules():
    """Get a formatted list of available modules."""
    registry = get_registry()
    if not registry["modules"]:
        return "No reusable modules have been created yet."

    lines = ["Available modules:"]
    for mod in registry["modules"]:
        lines.append(f"\n- **{mod['name']}** ({mod['file']})")
        lines.append(f"  {mod['description']}")
        lines.append(f"  Functions: {', '.join(mod['functions'])}")

    return "\n".join(lines)
