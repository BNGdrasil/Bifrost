# --------------------------------------------------------------------------
# Admin Observability API - fixed summaries read from Prometheus
#
# @author bnbong bbbong9@gmail.com
#
# The gateway does not accept PromQL from a caller. Every query in this module
# is a constant written below, so the admin console can read a backup summary
# and the firing alerts without turning Bifrost into an unauthenticated query
# proxy in front of the monitoring stack.
#
# Every call here uses its own short lived HTTP client with its own timeout.
# The proxy and the auth checks share the process wide client, and a slow or
# unreachable monitoring backend must not consume its connection pool.
# --------------------------------------------------------------------------
import asyncio
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Request, status

from src.core.config import settings
from src.core.permissions import require_admin
from src.schemas.observability import (
    AlertmanagerStatus,
    AlertsObservability,
    BackupComponentStatus,
    BackupObservability,
    FiringAlert,
)

router = APIRouter()
logger = structlog.get_logger()

PROMETHEUS_QUERY_PATH = "/api/v1/query"
PROMETHEUS_ALERTS_PATH = "/api/v1/alerts"
ALERTMANAGER_ALERTS_PATH = "/api/v2/alerts"

# Metric names written by the baedalus backup scripts through the node
# exporter textfile collector, mapped to the response field each one fills.
# The names and the `component` label were read from baedalus
# backup/lib/common.sh and monitoring/prometheus/rules/basic.yml; nothing that
# is not produced there is queried.
BACKUP_METRIC_FIELDS = {
    "bngdrasil_backup_last_success_timestamp_seconds": "last_success_timestamp",
    "bngdrasil_backup_last_run_timestamp_seconds": "last_run_timestamp",
    "bngdrasil_backup_last_run_status": "last_run_status",
    "bngdrasil_backup_unshipped_total": "unshipped_total",
}

# The one query this endpoint sends, built from the names above so the two
# cannot drift apart. A Prometheus label regex is anchored, so the alternation
# matches those four names and nothing else. It reads as:
#   {__name__=~"bngdrasil_backup_last_run_status|..."}
BACKUP_METRIC_QUERY = '{{__name__=~"{}"}}'.format(
    "|".join(sorted(BACKUP_METRIC_FIELDS))
)

NOT_CONFIGURED_DETAIL = (
    "Observability summaries are not available because PROMETHEUS_URL is not "
    "set. Configure it with the address of the Prometheus server on the "
    "monitoring network, or query Prometheus and Grafana directly."
)

# Prometheus writes timestamps with nanosecond precision, and
# datetime.fromisoformat accepts at most microseconds.
_OVERLONG_FRACTION = re.compile(r"(\.\d{6})\d+")


class ObservabilityBackendError(RuntimeError):
    """Raised when an observability backend cannot be read."""


def create_observability_client(
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> httpx.AsyncClient:
    """Create the dedicated client used for one observability request.

    The transport argument exists so that tests drive this exact
    configuration against recorded Prometheus and Alertmanager responses.
    """
    return httpx.AsyncClient(
        timeout=settings.OBSERVABILITY_QUERY_TIMEOUT_SECONDS,
        follow_redirects=False,
        transport=transport,
    )


def _parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse an RFC 3339 timestamp, tolerating nanosecond precision."""
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = _OVERLONG_FRACTION.sub(r"\1", value.strip())
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _label(labels: Mapping[str, Any], name: str) -> Optional[str]:
    """Read one alert label, treating an absent or empty value as unset."""
    value = labels.get(name)
    return str(value) if value else None


def _sample_value(sample: Mapping[str, Any]) -> Optional[float]:
    """Read the numeric value out of one instant vector sample."""
    pair = sample.get("value")
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return None
    try:
        number = float(pair[1])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        # Prometheus spells a missing or undefined value as NaN or Inf. That
        # is not a measurement, so it is reported as "not measured".
        return None
    return number


async def _get_json(client: httpx.AsyncClient, url: str, description: str) -> Any:
    """Fetch and decode one JSON document, converting every failure.

    The configured timeout is a ceiling on the whole call. The httpx timeout
    alone would grant it to each transport stage separately, so a backend that
    is slow at connecting, at sending and at answering could hold the request
    for several times the configured budget. asyncio.wait_for closes that gap,
    and the client timeout stays as the inner backstop.
    """
    budget = settings.OBSERVABILITY_QUERY_TIMEOUT_SECONDS
    try:
        response = await asyncio.wait_for(client.get(url), timeout=budget)
    except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
        raise ObservabilityBackendError(
            f"{description} timed out after {budget} seconds"
        ) from exc
    except httpx.HTTPError as exc:
        raise ObservabilityBackendError(f"{description} failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - nothing may escape to the caller
        raise ObservabilityBackendError(f"{description} failed: {exc}") from exc

    try:
        payload = response.json()
    except ValueError:
        payload = None

    if response.status_code != 200:
        reason = ""
        if isinstance(payload, Mapping):
            reason = str(payload.get("error") or payload.get("message") or "")
        suffix = f": {reason}" if reason else ""
        raise ObservabilityBackendError(
            f"{description} answered HTTP {response.status_code}{suffix}"
        )

    if payload is None:
        raise ObservabilityBackendError(
            f"{description} answered a body that is not JSON"
        )
    return payload


async def _query_prometheus(
    client: httpx.AsyncClient, base_url: str, query: str
) -> List[Mapping[str, Any]]:
    """Run one instant query and return its samples."""
    url = str(httpx.URL(base_url + PROMETHEUS_QUERY_PATH, params={"query": query}))
    payload = await _get_json(client, url, "Prometheus query")

    if not isinstance(payload, Mapping) or payload.get("status") != "success":
        reason = ""
        if isinstance(payload, Mapping):
            reason = str(payload.get("error") or "")
        suffix = f": {reason}" if reason else ""
        raise ObservabilityBackendError(f"Prometheus query was refused{suffix}")

    data = payload.get("data")
    result = data.get("result") if isinstance(data, Mapping) else None
    if not isinstance(result, list):
        raise ObservabilityBackendError(
            "Prometheus query answered without a result vector"
        )
    return [sample for sample in result if isinstance(sample, Mapping)]


def _build_backup_summary(
    samples: List[Mapping[str, Any]], queried_at: datetime
) -> BackupObservability:
    """Fold the query samples into one row per reporting series.

    A row is keyed by component, instance and job together rather than by
    component alone. The same component name is reported by more than one
    host once a service moves or a second node runs its own backup, and
    folding those into one row let the sample that happened to come last
    overwrite the earlier one, so one host's failure could be hidden behind
    another host's success.
    """
    rows: Dict[Tuple[str, Optional[str], Optional[str]], Dict[str, Any]] = {}
    # Fields already seen for one key, kept apart from the row because a
    # sample whose value is not a measurement writes nothing into the row.
    seen: Dict[Tuple[str, Optional[str], Optional[str]], Set[str]] = {}
    for sample in samples:
        metric = sample.get("metric")
        if not isinstance(metric, Mapping):
            continue
        field = BACKUP_METRIC_FIELDS.get(str(metric.get("__name__")))
        component = metric.get("component")
        if field is None or not component:
            continue

        key = (
            str(component),
            _label(metric, "instance"),
            _label(metric, "job"),
        )
        row = rows.setdefault(
            key,
            {"component": key[0], "instance": key[1], "job": key[2]},
        )

        if field in seen.setdefault(key, set()):
            # Prometheus returns one sample per series, so a repeated field on
            # one key means the payload did not come from a query this module
            # sent. The later value wins, and the collision is recorded.
            logger.warning(
                "Duplicate backup metric sample",
                component=key[0],
                instance=key[1],
                job=key[2],
                field=field,
            )
        seen[key].add(field)

        value = _sample_value(sample)
        if value is not None:
            row[field] = value

    now = queried_at.timestamp()
    components = []
    for key in sorted(rows, key=lambda item: (item[0], item[1] or "", item[2] or "")):
        row = rows[key]
        last_success = row.get("last_success_timestamp")
        if last_success is not None:
            row["age_seconds"] = now - last_success
        components.append(BackupComponentStatus(**row))

    note = None
    if not components:
        note = (
            "Prometheus holds no bngdrasil_backup_* series yet. The backup "
            "jobs have not reported through the node exporter textfile "
            "collector, so no component state is known."
        )

    return BackupObservability(
        available=bool(components),
        queried_at=queried_at,
        components=components,
        note=note,
    )


def _firing_alerts(payload: Any) -> List[Tuple[Dict[str, str], FiringAlert]]:
    """Extract the firing alerts from a Prometheus /api/v1/alerts payload.

    Alerts in the `pending` state are dropped: they have not completed their
    `for` duration, so Prometheus has not notified anything about them yet.
    """
    if not isinstance(payload, Mapping) or payload.get("status") != "success":
        raise ObservabilityBackendError("Prometheus alert listing was refused")
    data = payload.get("data")
    raw = data.get("alerts") if isinstance(data, Mapping) else None
    if not isinstance(raw, list):
        raise ObservabilityBackendError(
            "Prometheus alert listing answered without an alert list"
        )

    extracted: List[Tuple[Dict[str, str], FiringAlert]] = []
    for alert in raw:
        if not isinstance(alert, Mapping) or alert.get("state") != "firing":
            continue
        labels = alert.get("labels")
        labels = labels if isinstance(labels, Mapping) else {}
        annotations = alert.get("annotations")
        annotations = annotations if isinstance(annotations, Mapping) else {}
        alertname = labels.get("alertname")
        if not alertname:
            continue

        # The rules in baedalus set severity on every alert, instance and job
        # come from the scrape target, component distinguishes one backup from
        # another, and service is carried by the per service rules.
        summary = annotations.get("summary")
        extracted.append(
            (
                {str(key): str(value) for key, value in labels.items()},
                FiringAlert(
                    alertname=str(alertname),
                    severity=_label(labels, "severity"),
                    instance=_label(labels, "instance"),
                    service=_label(labels, "service"),
                    job=_label(labels, "job"),
                    component=_label(labels, "component"),
                    active_at=_parse_timestamp(alert.get("activeAt")),
                    summary=str(summary) if summary else None,
                ),
            )
        )
    return extracted


def _suppression_states(
    payload: Any,
) -> List[Tuple[Dict[str, str], Tuple[bool, bool]]]:
    """Read the silenced and inhibited flags out of an Alertmanager listing."""
    if not isinstance(payload, list):
        raise ObservabilityBackendError(
            "Alertmanager answered something other than an alert list"
        )

    states: List[Tuple[Dict[str, str], Tuple[bool, bool]]] = []
    for alert in payload:
        if not isinstance(alert, Mapping):
            continue
        labels = alert.get("labels")
        if not isinstance(labels, Mapping):
            continue
        state = alert.get("status")
        state = state if isinstance(state, Mapping) else {}
        silenced = bool(state.get("silencedBy"))
        inhibited = bool(state.get("inhibitedBy"))
        states.append(
            (
                {str(key): str(value) for key, value in labels.items()},
                (silenced, inhibited),
            )
        )
    return states


def _match_suppression(
    labels: Mapping[str, str],
    states: List[Tuple[Dict[str, str], Tuple[bool, bool]]],
) -> Tuple[Optional[bool], Optional[bool]]:
    """Find the Alertmanager entry that carries the same alert.

    Alertmanager holds the external labels Prometheus attaches on delivery
    (cluster and environment here), so its label set is a superset of the one
    the rule evaluated. Matching therefore asks whether the Alertmanager entry
    contains every label of the firing alert, not whether the two are equal.

    That test alone is not enough to name one entry, because every entry that
    merely adds labels also passes it. The closest entry is taken instead: the
    one carrying the fewest labels the firing alert does not have, since
    Alertmanager only adds the external labels to what the rule evaluated.
    An entry with further labels beyond those describes a different alert and
    loses to the exact one.

    Two entries that are equally close, which is what two entries differing
    only in an external label are, leave the state unknown. Returning the
    first of them made the answer depend on the order Alertmanager happened
    to list its alerts in, and that order is not a fact about suppression.

    No match at all is also unknown, not "not suppressed". An alert still
    inside the group wait has not reached Alertmanager, so Alertmanager has
    said nothing about whether a silence covers it.
    """
    scored: List[Tuple[int, Tuple[bool, bool]]] = []
    for candidate, state in states:
        if not all(candidate.get(key) == value for key, value in labels.items()):
            continue
        extra = sum(1 for key in candidate if key not in labels)
        scored.append((extra, state))

    if not scored:
        return (None, None)

    best = min(score for score, _ in scored)
    winners = [state for score, state in scored if score == best]
    if len(winners) != 1:
        logger.warning(
            "Alertmanager suppression state is ambiguous",
            alertname=labels.get("alertname"),
            candidates=len(winners),
        )
        return (None, None)
    return winners[0]


@router.get("/observability/backups", response_model=BackupObservability)
@require_admin
async def get_backup_observability(request: Request) -> BackupObservability:
    """Summarise the backup state of every component (Admin only).

    The values come from the bngdrasil_backup_* series the backup jobs publish
    through the node exporter textfile collector. A component that has never
    reported a field gets null there rather than a zero, and an empty
    component list is returned with available=false rather than as a healthy
    looking result.
    """
    base_url = settings.PROMETHEUS_URL
    if not base_url:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=NOT_CONFIGURED_DETAIL,
        )

    queried_at = datetime.now(timezone.utc)
    try:
        async with create_observability_client() as client:
            samples = await _query_prometheus(client, base_url, BACKUP_METRIC_QUERY)
    except ObservabilityBackendError as exc:
        logger.warning("Backup observability query failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Prometheus could not be read: {exc}",
        )
    except Exception as exc:  # noqa: BLE001 - one endpoint must not break others
        logger.error("Backup observability query raised", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Prometheus could not be read: {exc}",
        )

    return _build_backup_summary(samples, queried_at)


@router.get("/observability/alerts", response_model=AlertsObservability)
@require_admin
async def get_alert_observability(request: Request) -> AlertsObservability:
    """List the alerts that are firing right now (Admin only).

    Prometheus is the source of the alert list, because it evaluates the rules
    and is always present. When ALERTMANAGER_URL is configured the silenced
    and inhibited flags are added from Alertmanager. A failed Alertmanager
    lookup is reported in the alertmanager field and does not fail the
    request, since the firing alerts themselves are still correct without it.
    """
    base_url = settings.PROMETHEUS_URL
    if not base_url:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=NOT_CONFIGURED_DETAIL,
        )

    alertmanager_url = settings.ALERTMANAGER_URL
    queried_at = datetime.now(timezone.utc)

    try:
        async with create_observability_client() as client:
            payload = await _get_json(
                client,
                base_url + PROMETHEUS_ALERTS_PATH,
                "Prometheus alert listing",
            )
            firing = _firing_alerts(payload)

            alertmanager = AlertmanagerStatus(
                configured=bool(alertmanager_url), available=False
            )
            states: List[Tuple[Dict[str, str], Tuple[bool, bool]]] = []
            if alertmanager_url:
                try:
                    states = _suppression_states(
                        await _get_json(
                            client,
                            alertmanager_url + ALERTMANAGER_ALERTS_PATH,
                            "Alertmanager alert listing",
                        )
                    )
                    alertmanager = AlertmanagerStatus(configured=True, available=True)
                except ObservabilityBackendError as exc:
                    logger.warning("Alertmanager lookup failed", error=str(exc))
                    alertmanager = AlertmanagerStatus(
                        configured=True, available=False, error=str(exc)
                    )
    except ObservabilityBackendError as exc:
        logger.warning("Alert observability query failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Prometheus could not be read: {exc}",
        )
    except Exception as exc:  # noqa: BLE001 - one endpoint must not break others
        logger.error("Alert observability query raised", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Prometheus could not be read: {exc}",
        )

    alerts = []
    for labels, alert in firing:
        if alertmanager.available:
            alert.silenced, alert.inhibited = _match_suppression(labels, states)
        alerts.append(alert)

    return AlertsObservability(
        queried_at=queried_at,
        firing_count=len(alerts),
        alerts=alerts,
        alertmanager=alertmanager,
    )
