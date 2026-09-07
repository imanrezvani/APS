"""Package version resolution for the APS Engine API.

The version is read from the installed distribution metadata
(``importlib.metadata``), whose single source of truth is ``pyproject.toml``,
so the API never duplicates the version manually. When the distribution is
not installed (e.g. running straight from a source checkout) it falls back
to the ``aps_engine.__version__`` attribute.
"""

from importlib.metadata import PackageNotFoundError, version as _distribution_version

DISTRIBUTION_NAME = "aps-engine"


def get_service_name() -> str:
    """The canonical distribution/service name."""
    return DISTRIBUTION_NAME


def get_package_version() -> str:
    """The current APS Engine version string."""
    try:
        return _distribution_version(DISTRIBUTION_NAME)
    except PackageNotFoundError:  # pragma: no cover - source checkout fallback
        from aps_engine import __version__ as engine_version

        return engine_version
