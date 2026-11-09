"""Library ingest core. ``run_ingest``, ``PlanEntry`` and ``IngestReport`` are
loaded lazily so importing the package does not pull in the AI client stack."""

__all__ = ["run_ingest", "PlanEntry", "IngestReport"]


def __getattr__(name):
    if name in __all__:
        from src.library.ingest_core import runner

        return getattr(runner, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
