# --------------------------------------------------------------------------
# Prometheus metrics for the API Gateway service
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from typing import Any, List, Optional

from prometheus_client import REGISTRY, Counter, Histogram

# Label used when a proxied request targets an unregistered service.
UNKNOWN_SERVICE = "unknown"
# Only standard methods become labels. An arbitrary method from the wire would
# otherwise be an unbounded label source.
STANDARD_METHODS = frozenset(
    {
        "GET",
        "HEAD",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
        "TRACE",
        "CONNECT",
    }
)
OTHER_METHOD = "OTHER"
# Label used for gateway endpoints that are not a proxied upstream call.
GATEWAY_SERVICE = "gateway"


def _get_or_create(
    metric_cls: Any, name: str, documentation: str, labelnames: List[str], **kwargs: Any
) -> Any:
    """Return an existing collector instead of failing on re-import.

    The test suite creates the application several times in one process, which
    would otherwise raise a duplicate registration error.
    """
    try:
        return metric_cls(name, documentation, labelnames, **kwargs)
    except ValueError:
        existing = REGISTRY._names_to_collectors.get(name)
        if existing is None:
            # Counters register their collector under the "_total" free name.
            existing = REGISTRY._names_to_collectors.get(f"{name}_total")
        return existing


# The service label is bounded by the number of registered services, so the
# request path itself is deliberately not used as a label.
REQUEST_COUNT = _get_or_create(
    Counter,
    "http_requests_total",
    "Total HTTP requests handled by the gateway",
    ["method", "service", "status_class"],
)

REQUEST_LATENCY = _get_or_create(
    Histogram,
    "http_request_duration_seconds",
    "HTTP request latency handled by the gateway",
    ["method", "service"],
)


def method_label(method: str) -> str:
    """Bucket a request method into the standard set to bound cardinality."""
    normalised = (method or "").upper()
    return normalised if normalised in STANDARD_METHODS else OTHER_METHOD


def status_class(status_code: int) -> str:
    """Bucket a status code into 2xx style classes to bound cardinality."""
    return f"{status_code // 100}xx"


def record_request(
    method: str, service: Optional[str], status_code: int, duration: float
) -> None:
    """Record one handled request."""
    label = service or GATEWAY_SERVICE
    verb = method_label(method)
    if REQUEST_COUNT is not None:
        REQUEST_COUNT.labels(
            method=verb, service=label, status_class=status_class(status_code)
        ).inc()
    if REQUEST_LATENCY is not None:
        REQUEST_LATENCY.labels(method=verb, service=label).observe(duration)
