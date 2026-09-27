"""Domain services shared by the API routers.

``app.core`` re-exports every name defined here, so routers keep importing
``from ..core import ...``. Service modules import only from sibling services
and from lower-level ``app.*`` modules -- never from ``app.core`` or
``app.main`` -- so importing any router (or any service) on its own cannot hit
a circular import.

A test that patches a name must target the module whose globals the calling
code reads: code in ``app.services.query_tools`` looks up
``EXTERNAL_QUERY_TOOL_RATE_LIMIT_PER_MINUTE`` there, while routers that call
``main.execute_connector_query(...)`` (``main`` being ``app.core``) still see a
patch on ``app.core.execute_connector_query``.
"""
