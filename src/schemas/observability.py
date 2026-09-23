# --------------------------------------------------------------------------
# Observability summary schemas for the admin API
#
# @author bnbong bbbong9@gmail.com
#
# These models describe the fixed observability summaries the admin API
# computes from Prometheus and Alertmanager. They are deliberately narrow:
# the gateway runs a small set of hard coded queries and reports what it read,
# so no caller can turn this into an arbitrary query proxy.
# --------------------------------------------------------------------------
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class BackupComponentStatus(BaseModel):
    """Backup state of one component, as last reported to Prometheus.

    One row describes one component on one reporting target, so the same
    component name appears more than once when two hosts report it. The row
    is identified by component, instance and job together.

    Every measured field is optional. The backup scripts write a metric only
    once they have something to report: a component that has never succeeded
    has no last success timestamp, and the offsite shipping component has no
    unshipped counter at all. Those gaps are reported as null instead of zero,
    because zero would read as "nothing is waiting" rather than "this was
    never measured".
    """

    component: str
    instance: Optional[str] = None
    job: Optional[str] = None
    last_success_timestamp: Optional[float] = None
    last_run_timestamp: Optional[float] = None
    # 0 means the last run succeeded and 1 means it failed, following
    # bngdrasil_backup_last_run_status.
    last_run_status: Optional[float] = None
    unshipped_total: Optional[float] = None
    # Seconds between the last successful backup and the time this response
    # was built, measured against the gateway clock.
    age_seconds: Optional[float] = None


class BackupObservability(BaseModel):
    """Summary of every backup component Prometheus currently knows about."""

    # False when Prometheus answered but holds no backup series yet. The
    # component list is then empty, and that emptiness means "never reported",
    # not "everything is at zero".
    available: bool
    queried_at: datetime
    components: List[BackupComponentStatus]
    # Explains an available=false answer in one sentence.
    note: Optional[str] = None


class AlertmanagerStatus(BaseModel):
    """Outcome of the optional Alertmanager lookup.

    Alertmanager is not required for this endpoint. When it is not configured
    or cannot be reached, the firing alerts are still returned and this field
    carries the reason, so a silenced alert is never mistaken for an alert
    that Alertmanager confirmed is not silenced.
    """

    configured: bool
    available: bool
    error: Optional[str] = None


class FiringAlert(BaseModel):
    """One alert Prometheus reports as firing.

    Alerts that are still in the `pending` state are not included: they have
    not passed their `for` duration and are not notified either.
    """

    alertname: str
    severity: Optional[str] = None
    instance: Optional[str] = None
    service: Optional[str] = None
    job: Optional[str] = None
    # The backup rules carry the component label, and it is the only way to
    # tell one stale backup apart from another on the same host.
    component: Optional[str] = None
    active_at: Optional[datetime] = Field(
        default=None,
        description=(
            "Prometheus activeAt: the moment the alert condition first "
            "evaluated to true, which is when the `for` wait started and not "
            "when the alert began firing. An alert with `for: 5m` therefore "
            "reports a value five minutes older than the time it was "
            "notified."
        ),
    )
    summary: Optional[str] = None
    # Null when Alertmanager was not consulted, so an unknown suppression
    # state is never reported as "not suppressed".
    silenced: Optional[bool] = Field(
        default=None,
        description=(
            "True when Alertmanager reports a silence covering this alert. "
            "Null when Alertmanager was not consulted, could not be reached, "
            "or holds no single entry that matches this alert, so an unknown "
            "state is never reported as 'not silenced'."
        ),
    )
    inhibited: Optional[bool] = Field(
        default=None,
        description=(
            "True when Alertmanager reports an inhibition covering this "
            "alert. Null carries the same meaning as on silenced."
        ),
    )


class AlertsObservability(BaseModel):
    """Summary of the alerts that are firing right now."""

    queried_at: datetime
    firing_count: int
    alerts: List[FiringAlert]
    alertmanager: AlertmanagerStatus
