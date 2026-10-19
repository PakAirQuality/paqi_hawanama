"""
Canonical ingestion package.

This is the ONLY place ingestion code lives. The FastAPI task endpoints and the
standalone worker shims (apps/worker/*.py) both import from here. The old
apps/worker/{tasks,services,config} copies and the Dockerfile COPY overlay that
used to paste them over this package are gone; `provenance.assert_canonical()`
fails the build if either ever comes back.
"""
