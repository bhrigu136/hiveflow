"""Application logging configuration.

`logging` was imported in the app factory but never configured, so the six
`current_app.logger` calls in the codebase went to Flask's default handler with
no formatter, no level control and no request correlation — and on a PaaS,
unformatted stdout is retained only briefly.

Every log line carries a short request id so the lines belonging to one request
can be grouped after the fact. Outside a request context the id reads '-'.
"""
import logging
import sys
import uuid

from flask import g, has_request_context, request

LOG_FORMAT = (
    '%(asctime)s %(levelname)-8s [%(request_id)s] '
    '%(name)s %(method)s %(path)s — %(message)s'
)


class RequestContextFilter(logging.Filter):
    """Attach request id, method and path to every record.

    Records emitted outside a request context still need these attributes,
    otherwise the formatter raises KeyError.
    """

    def filter(self, record):
        if has_request_context():
            record.request_id = getattr(g, 'request_id', '-')
            record.method = request.method
            record.path = request.path
        else:
            record.request_id = '-'
            record.method = '-'
            record.path = '-'
        return True


def configure_logging(app):
    """Attach a single stdout handler with a request-aware formatter."""
    level_name = app.config.get('LOG_LEVEL', 'INFO')
    level = getattr(logging, str(level_name).upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.addFilter(RequestContextFilter())

    # Replace Flask's default handler rather than adding to it, so each line is
    # emitted once and in one format.
    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(level)
    app.logger.propagate = False

    @app.before_request
    def _assign_request_id():
        # Honour an upstream id when the proxy supplies one, so logs can be
        # correlated across services; otherwise mint a short one.
        g.request_id = request.headers.get('X-Request-ID') or uuid.uuid4().hex[:8]

    return app.logger
