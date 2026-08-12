"""Watch a dispatched release build, then release and deploy.

The dispatch-driven promote flow.  ``_handle_promote`` dispatches the
project's *Release workflow* (the ``artifact_workflow`` capability
option) and returns immediately; the work of waiting for that build and
acting on its outcome lives here, because a release build takes minutes
and cannot block a request handler.

:mod:`imbi.api.release_promote.queue` is the Valkey-stream consumer;
:mod:`imbi.api.release_promote.service` holds the poll loop and the
status the UI reads back.
"""
