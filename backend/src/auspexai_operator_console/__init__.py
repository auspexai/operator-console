"""AuspexAI operator console — maintainer's privileged dashboard.

O-M1 (this milestone): scaffold the FastAPI backend + SvelteKit static
frontend; ship a placeholder page at https://ops.auspexai.network.
NO auth gating yet — that's O-M2.
"""

from __future__ import annotations

from importlib.metadata import version as _v

# Git-derived (hatch-vcs); read from installed metadata. See version_provenance.md.
__version__ = _v("auspexai-operator-console")
