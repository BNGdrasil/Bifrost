# --------------------------------------------------------------------------
# Tests for the admin observability summaries (P2-A)
#
# @author bnbong bbbong9@gmail.com
#
# The recorded payloads under tests/fixtures were captured from a Prometheus
# v3.7.2 and an Alertmanager v0.28.1 container running the same rule file and
# the same backup metric names as the baedalus deployment. A hand written mock
# would agree with the code instead of with the servers, and the previous
# review round found a bug exactly there.
# --------------------------------------------------------------------------
import asyncio
import copy
import json
import pathlib
import time
from typing import Any, Callable, Dict, Optional

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from src.core.config import settings

ADMIN_HEADERS = {"Authorization": "Bearer admin-token"}

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

PROMETHEUS_URL = "http://prometheus:9090"
ALERTMANAGER_URL = "http://alertmanager:9093"


def load_fixture(name: str) -> Any:
    """Read one recorded backend response."""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def install_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    """Route every observability call through a recorded response handler."""
    from src.api.admin import observability

    real_factory = observability.create_observability_client

    def factory(
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> httpx.AsyncClient:
        return real_factory(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(observability, "create_observability_client", factory)


def recorded_backend(
    query: Any = None,
    alerts: Any = None,
    alertmanager: Any = None,
    query_status: int = 200,
    alertmanager_status: int = 200,
) -> Callable[[httpx.Request], httpx.Response]:
    """Build a handler that answers each backend path with a recorded body."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/query":
            assert query is not None, "unexpected Prometheus query"
            return httpx.Response(query_status, json=query)
        if path == "/api/v1/alerts":
            assert alerts is not None, "unexpected Prometheus alert listing"
            return httpx.Response(200, json=alerts)
        if path == "/api/v2/alerts":
            assert alertmanager is not None, "unexpected Alertmanager listing"
            return httpx.Response(alertmanager_status, json=alertmanager)
        raise AssertionError(f"unexpected observability request to {path}")

    return handler


@pytest.fixture
def prometheus_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PROMETHEUS_URL", PROMETHEUS_URL)
    monkeypatch.setattr(settings, "ALERTMANAGER_URL", None)


@pytest.fixture
def both_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PROMETHEUS_URL", PROMETHEUS_URL)
    monkeypatch.setattr(settings, "ALERTMANAGER_URL", ALERTMANAGER_URL)


class TestBackupSummary:
    """The backup summary must report what Prometheus actually holds"""

    @pytest.mark.asyncio
    async def test_components_are_folded_from_the_recorded_query(
        self,
        client: AsyncClient,
        mock_auth_admin,
        monkeypatch: pytest.MonkeyPatch,
        prometheus_configured: None,
    ):
        install_transport(
            monkeypatch,
            recorded_backend(query=load_fixture("prometheus_query_backups")),
        )

        response = await client.get(
            "/admin/api/observability/backups", headers=ADMIN_HEADERS
        )
        assert response.status_code == 200
        body = response.json()
        assert body["available"] is True
        assert body["note"] is None

        rows: Dict[str, Any] = {row["component"]: row for row in body["components"]}
        assert sorted(rows) == [
            "all",
            "postgresql",
            "redis-vm3",
            "ship",
            "sqlite-grafana",
        ]

        postgresql = rows["postgresql"]
        assert postgresql["instance"] == "vm3-node:9100"
        assert postgresql["job"] == "vm3-node"
        assert postgresql["last_success_timestamp"] == 1758600000
        assert postgresql["last_run_timestamp"] == 1758600000
        assert postgresql["last_run_status"] == 0
        assert postgresql["unshipped_total"] == 6
        assert postgresql["age_seconds"] > 0

    @pytest.mark.asyncio
    async def test_a_missing_metric_is_null_and_not_zero(
        self,
        client: AsyncClient,
        mock_auth_admin,
        monkeypatch: pytest.MonkeyPatch,
        prometheus_configured: None,
    ):
        """The offsite shipping component publishes no unshipped counter.

        Reporting zero there would read as "nothing is waiting to be shipped",
        which is a claim the backup scripts never made.
        """
        install_transport(
            monkeypatch,
            recorded_backend(query=load_fixture("prometheus_query_backups")),
        )

        response = await client.get(
            "/admin/api/observability/backups", headers=ADMIN_HEADERS
        )
        rows = {row["component"]: row for row in response.json()["components"]}

        assert rows["ship"]["unshipped_total"] is None
        # The "all" component reports a run but has never reported a success.
        assert rows["all"]["last_success_timestamp"] is None
        assert rows["all"]["age_seconds"] is None
        assert rows["all"]["last_run_status"] == 1

    @pytest.mark.asyncio
    async def test_two_instances_of_one_component_are_separate_rows(
        self,
        client: AsyncClient,
        mock_auth_admin,
        monkeypatch: pytest.MonkeyPatch,
        prometheus_configured: None,
    ):
        """The same component on two hosts must not collapse into one row.

        The recording duplicates the postgresql series onto a second node.
        Folding by component alone let whichever series came last overwrite
        the other, so a failing host was hidden behind a healthy one.
        """
        install_transport(
            monkeypatch,
            recorded_backend(
                query=load_fixture("prometheus_query_backups_two_instances")
            ),
        )

        response = await client.get(
            "/admin/api/observability/backups", headers=ADMIN_HEADERS
        )
        assert response.status_code == 200
        components = response.json()["components"]

        postgresql = [row for row in components if row["component"] == "postgresql"]
        assert len(postgresql) == 2
        by_instance = {row["instance"]: row for row in postgresql}

        assert by_instance["vm3-node:9100"]["job"] == "vm3-node"
        assert by_instance["vm3-node:9100"]["last_run_status"] == 0
        assert by_instance["vm3-node:9100"]["last_success_timestamp"] == 1758600000
        assert by_instance["vm3-node:9100"]["unshipped_total"] == 6

        assert by_instance["vm4-node:9100"]["job"] == "vm4-node"
        assert by_instance["vm4-node:9100"]["last_run_status"] == 1
        assert by_instance["vm4-node:9100"]["last_success_timestamp"] == 1758500000
        assert by_instance["vm4-node:9100"]["unshipped_total"] == 9

        # Every other component keeps exactly one row, and the response still
        # carries one entry per reporting series.
        assert len(components) == 6

    def test_a_repeated_field_on_one_key_is_logged(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Two samples of one field on one key cannot come from Prometheus.

        Prometheus answers an instant query with one sample per series, so a
        repeat means the payload did not come from the query this module
        sent. The later value is kept and the collision is recorded.
        """
        from datetime import datetime, timezone

        from src.api.admin import observability

        recorded = []

        class RecordingLogger:
            def warning(self, event, **fields):
                recorded.append((event, fields))

        monkeypatch.setattr(observability, "logger", RecordingLogger())

        def sample(value: str):
            return {
                "metric": {
                    "__name__": "bngdrasil_backup_last_run_status",
                    "component": "postgresql",
                    "instance": "vm3-node:9100",
                    "job": "vm3-node",
                },
                "value": [1790097311.701, value],
            }

        summary = observability._build_backup_summary(
            [sample("0"), sample("1")], datetime.now(timezone.utc)
        )

        assert len(summary.components) == 1
        assert summary.components[0].last_run_status == 1
        assert recorded and recorded[0][0] == "Duplicate backup metric sample"
        assert recorded[0][1]["field"] == "last_run_status"
        assert recorded[0][1]["instance"] == "vm3-node:9100"

    @pytest.mark.asyncio
    async def test_no_series_is_reported_as_unavailable(
        self,
        client: AsyncClient,
        mock_auth_admin,
        monkeypatch: pytest.MonkeyPatch,
        prometheus_configured: None,
    ):
        install_transport(
            monkeypatch,
            recorded_backend(query=load_fixture("prometheus_query_empty")),
        )

        response = await client.get(
            "/admin/api/observability/backups", headers=ADMIN_HEADERS
        )
        assert response.status_code == 200
        body = response.json()
        assert body["available"] is False
        assert body["components"] == []
        assert body["note"]

    @pytest.mark.asyncio
    async def test_the_query_is_a_constant_and_not_caller_supplied(
        self,
        client: AsyncClient,
        mock_auth_admin,
        monkeypatch: pytest.MonkeyPatch,
        prometheus_configured: None,
    ):
        from src.api.admin.observability import BACKUP_METRIC_QUERY

        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.params.get("query"))
            return httpx.Response(200, json=load_fixture("prometheus_query_empty"))

        install_transport(monkeypatch, handler)

        response = await client.get(
            "/admin/api/observability/backups?query=up&component=x",
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        # The query parameters of the admin request reach neither the query
        # nor anything else that is sent to Prometheus.
        assert seen == [BACKUP_METRIC_QUERY]
        assert BACKUP_METRIC_QUERY.startswith('{__name__=~"bngdrasil_backup_')

    @pytest.mark.asyncio
    async def test_a_refused_query_becomes_502(
        self,
        client: AsyncClient,
        mock_auth_admin,
        monkeypatch: pytest.MonkeyPatch,
        prometheus_configured: None,
    ):
        install_transport(
            monkeypatch,
            recorded_backend(
                query=load_fixture("prometheus_query_error"), query_status=400
            ),
        )

        response = await client.get(
            "/admin/api/observability/backups", headers=ADMIN_HEADERS
        )
        assert response.status_code == 502
        assert "parse error" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_a_timeout_becomes_502(
        self,
        client: AsyncClient,
        mock_auth_admin,
        monkeypatch: pytest.MonkeyPatch,
        prometheus_configured: None,
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        install_transport(monkeypatch, handler)

        response = await client.get(
            "/admin/api/observability/backups", headers=ADMIN_HEADERS
        )
        assert response.status_code == 502
        assert "timed out" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_a_connection_failure_becomes_502(
        self,
        client: AsyncClient,
        mock_auth_admin,
        monkeypatch: pytest.MonkeyPatch,
        prometheus_configured: None,
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        install_transport(monkeypatch, handler)

        response = await client.get(
            "/admin/api/observability/backups", headers=ADMIN_HEADERS
        )
        assert response.status_code == 502

    @pytest.mark.asyncio
    async def test_an_unset_url_is_not_implemented(
        self, client: AsyncClient, mock_auth_admin, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "PROMETHEUS_URL", None)

        response = await client.get(
            "/admin/api/observability/backups", headers=ADMIN_HEADERS
        )
        assert response.status_code == 501
        assert "PROMETHEUS_URL" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_authentication_is_required(self, client: AsyncClient):
        response = await client.get("/admin/api/observability/backups")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_a_regular_user_is_rejected(
        self, client: AsyncClient, mock_auth_forbidden
    ):
        response = await client.get(
            "/admin/api/observability/backups", headers=ADMIN_HEADERS
        )
        assert response.status_code == 403


class TestAlertSummary:
    """Only firing alerts are reported, with real suppression states"""

    @pytest.mark.asyncio
    async def test_pending_alerts_are_not_reported_as_firing(
        self,
        client: AsyncClient,
        mock_auth_admin,
        monkeypatch: pytest.MonkeyPatch,
        prometheus_configured: None,
    ):
        install_transport(
            monkeypatch, recorded_backend(alerts=load_fixture("prometheus_alerts"))
        )

        response = await client.get(
            "/admin/api/observability/alerts", headers=ADMIN_HEADERS
        )
        assert response.status_code == 200
        body = response.json()

        # The recording holds five alerts, one of which is still pending.
        assert body["firing_count"] == 4
        assert len(body["alerts"]) == 4
        assert "BackupUnshippedPileup" not in {
            alert["alertname"] for alert in body["alerts"]
        }
        assert body["queried_at"]

    @pytest.mark.asyncio
    async def test_labels_and_annotations_are_carried(
        self,
        client: AsyncClient,
        mock_auth_admin,
        monkeypatch: pytest.MonkeyPatch,
        prometheus_configured: None,
    ):
        install_transport(
            monkeypatch, recorded_backend(alerts=load_fixture("prometheus_alerts"))
        )

        response = await client.get(
            "/admin/api/observability/alerts", headers=ADMIN_HEADERS
        )
        alerts = {
            (alert["alertname"], alert["component"]): alert
            for alert in response.json()["alerts"]
        }

        target_down = alerts[("TargetDown", None)]
        assert target_down["severity"] == "critical"
        assert target_down["instance"] == "gateway:8000"
        assert target_down["job"] == "msa-gateway"
        assert target_down["service"] is None
        assert target_down["summary"]
        # Prometheus writes nanosecond precision, which the naive parser
        # refuses. The timestamp must survive that.
        assert target_down["active_at"].startswith("2026-09-22T17:12:46")

    @pytest.mark.asyncio
    async def test_without_alertmanager_the_state_is_unknown(
        self,
        client: AsyncClient,
        mock_auth_admin,
        monkeypatch: pytest.MonkeyPatch,
        prometheus_configured: None,
    ):
        install_transport(
            monkeypatch, recorded_backend(alerts=load_fixture("prometheus_alerts"))
        )

        response = await client.get(
            "/admin/api/observability/alerts", headers=ADMIN_HEADERS
        )
        body = response.json()
        assert body["alertmanager"] == {
            "configured": False,
            "available": False,
            "error": None,
        }
        for alert in body["alerts"]:
            assert alert["silenced"] is None
            assert alert["inhibited"] is None

    @pytest.mark.asyncio
    async def test_alertmanager_adds_silenced_and_inhibited(
        self,
        client: AsyncClient,
        mock_auth_admin,
        monkeypatch: pytest.MonkeyPatch,
        both_configured: None,
    ):
        install_transport(
            monkeypatch,
            recorded_backend(
                alerts=load_fixture("prometheus_alerts"),
                alertmanager=load_fixture("alertmanager_alerts"),
            ),
        )

        response = await client.get(
            "/admin/api/observability/alerts", headers=ADMIN_HEADERS
        )
        body = response.json()
        assert body["alertmanager"]["available"] is True
        assert body["alertmanager"]["error"] is None

        states = {
            (alert["alertname"], alert["component"]): (
                alert["silenced"],
                alert["inhibited"],
            )
            for alert in body["alerts"]
        }
        assert states[("BackupStale", "postgresql")] == (False, False)
        assert states[("BackupStale", "redis-vm3")] == (True, False)
        assert states[("BackupStale", "sqlite-grafana")] == (False, True)
        assert states[("TargetDown", None)] == (False, False)

    @pytest.mark.asyncio
    async def test_a_failed_alertmanager_lookup_does_not_fail_the_request(
        self,
        client: AsyncClient,
        mock_auth_admin,
        monkeypatch: pytest.MonkeyPatch,
        both_configured: None,
    ):
        install_transport(
            monkeypatch,
            recorded_backend(
                alerts=load_fixture("prometheus_alerts"),
                alertmanager={"message": "service unavailable"},
                alertmanager_status=503,
            ),
        )

        response = await client.get(
            "/admin/api/observability/alerts", headers=ADMIN_HEADERS
        )
        assert response.status_code == 200
        body = response.json()
        assert body["firing_count"] == 4
        assert body["alertmanager"]["configured"] is True
        assert body["alertmanager"]["available"] is False
        assert "503" in body["alertmanager"]["error"]
        for alert in body["alerts"]:
            assert alert["silenced"] is None

    @pytest.mark.asyncio
    async def test_prometheus_failure_becomes_502(
        self,
        client: AsyncClient,
        mock_auth_admin,
        monkeypatch: pytest.MonkeyPatch,
        both_configured: None,
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        install_transport(monkeypatch, handler)

        response = await client.get(
            "/admin/api/observability/alerts", headers=ADMIN_HEADERS
        )
        assert response.status_code == 502

    @pytest.mark.asyncio
    async def test_an_unset_url_is_not_implemented(
        self, client: AsyncClient, mock_auth_admin, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "PROMETHEUS_URL", None)

        response = await client.get(
            "/admin/api/observability/alerts", headers=ADMIN_HEADERS
        )
        assert response.status_code == 501


class TestSuppressionMatching:
    """One Alertmanager entry must be named, or the state stays unknown"""

    @staticmethod
    def _states(payload):
        from src.api.admin.observability import _suppression_states

        return _suppression_states(payload)

    @staticmethod
    def _labels_of(payload, alertname: str, component: Optional[str] = None):
        for alert in payload:
            labels = alert["labels"]
            if labels["alertname"] != alertname:
                continue
            if component is not None and labels.get("component") != component:
                continue
            # The firing alert carries the rule labels only; Alertmanager adds
            # cluster and environment when Prometheus delivers the alert.
            return {
                key: value
                for key, value in labels.items()
                if key not in ("cluster", "environment")
            }
        raise AssertionError(f"{alertname} is not in the recording")

    def test_the_listing_order_does_not_change_the_answer(self):
        from src.api.admin.observability import _match_suppression

        payload = load_fixture("alertmanager_alerts")
        labels = self._labels_of(payload, "BackupStale", "redis-vm3")

        forward = _match_suppression(labels, self._states(payload))
        backward = _match_suppression(labels, self._states(list(reversed(payload))))

        assert forward == (True, False)
        assert backward == forward

    def test_an_unknown_alert_is_unknown_and_not_unsuppressed(self):
        """An alert inside the group wait has not reached Alertmanager yet."""
        from src.api.admin.observability import _match_suppression

        payload = load_fixture("alertmanager_alerts")
        labels = self._labels_of(payload, "BackupStale", "postgresql")
        labels["component"] = "never-delivered"

        assert _match_suppression(labels, self._states(payload)) == (None, None)

    def test_an_empty_alertmanager_listing_is_unknown(self):
        from src.api.admin.observability import _match_suppression

        payload = load_fixture("alertmanager_alerts")
        labels = self._labels_of(payload, "TargetDown")

        assert _match_suppression(labels, []) == (None, None)

    def test_two_equally_good_candidates_leave_the_state_unknown(self):
        """Entries differing only in a delivery label must not be guessed at.

        Both carry every label the rule evaluated, so neither is a better
        match than the other. Returning the first one made the answer depend
        on the order Alertmanager happened to list them in.
        """
        from src.api.admin.observability import _match_suppression

        payload = load_fixture("alertmanager_alerts")
        twin = copy.deepcopy(
            next(
                alert
                for alert in payload
                if alert["labels"]["alertname"] == "TargetDown"
            )
        )
        twin["labels"]["cluster"] = "chuncheon-standby"
        twin["status"]["silencedBy"] = ["3fd9eb7f-1b75-4540-9849-99ab9d5836c2"]
        ambiguous = payload + [twin]

        labels = self._labels_of(payload, "TargetDown")

        assert _match_suppression(labels, self._states(ambiguous)) == (None, None)
        assert _match_suppression(labels, self._states(list(reversed(ambiguous)))) == (
            None,
            None,
        )

    def test_the_closest_candidate_wins_over_a_broader_one(self):
        """An entry that only adds the delivery labels is not a tie.

        Alertmanager adds the external labels and nothing else, so the entry
        carrying only those is the same alert. An entry with a further label
        beyond them describes a different alert instance and must lose.
        """
        from src.api.admin.observability import _match_suppression

        labels = {"alertname": "BackupStale", "component": "postgresql"}
        delivered = {
            "alertname": "BackupStale",
            "component": "postgresql",
            "cluster": "chuncheon-main",
            "environment": "production",
        }
        broader = dict(delivered, instance="vm3-node:9100", job="vm3-node")
        states = [(broader, (True, False)), (delivered, (False, True))]

        assert _match_suppression(labels, states) == (False, True)
        assert _match_suppression(labels, list(reversed(states))) == (False, True)

    @pytest.mark.asyncio
    async def test_an_alert_alertmanager_does_not_know_stays_null(
        self,
        client: AsyncClient,
        mock_auth_admin,
        monkeypatch: pytest.MonkeyPatch,
        both_configured: None,
    ):
        alertmanager = [
            alert
            for alert in load_fixture("alertmanager_alerts")
            if alert["labels"].get("component") != "redis-vm3"
        ]
        install_transport(
            monkeypatch,
            recorded_backend(
                alerts=load_fixture("prometheus_alerts"), alertmanager=alertmanager
            ),
        )

        response = await client.get(
            "/admin/api/observability/alerts", headers=ADMIN_HEADERS
        )
        assert response.status_code == 200
        states = {
            (alert["alertname"], alert["component"]): (
                alert["silenced"],
                alert["inhibited"],
            )
            for alert in response.json()["alerts"]
        }
        assert states[("BackupStale", "redis-vm3")] == (None, None)
        assert states[("BackupStale", "postgresql")] == (False, False)


class TestTheTimeoutCapsTheWholeCall:
    """The configured budget bounds one backend call, not one stage of it"""

    @pytest.mark.asyncio
    async def test_a_slow_backend_becomes_502_within_the_budget(
        self,
        client: AsyncClient,
        mock_auth_admin,
        monkeypatch: pytest.MonkeyPatch,
        prometheus_configured: None,
    ):
        """A backend that answers slowly must not hold the request.

        httpx applies its timeout to each transport stage, so a backend that
        is slow inside one stage the mock transport does not model would run
        past the budget. asyncio.wait_for bounds the call itself.
        """
        monkeypatch.setattr(settings, "OBSERVABILITY_QUERY_TIMEOUT_SECONDS", 0.05)

        async def handler(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(5)
            return httpx.Response(200, json=load_fixture("prometheus_query_empty"))

        install_transport(monkeypatch, handler)

        started = time.monotonic()
        response = await client.get(
            "/admin/api/observability/backups", headers=ADMIN_HEADERS
        )
        elapsed = time.monotonic() - started

        assert response.status_code == 502
        assert "timed out after 0.05 seconds" in response.json()["detail"]
        assert elapsed < 2


class TestGatewayIsUnaffectedByAMonitoringOutage:
    """A dead Prometheus must stay inside the observability endpoints"""

    @pytest.mark.asyncio
    async def test_other_endpoints_answer_while_prometheus_is_down(
        self,
        app: FastAPI,
        client: AsyncClient,
        mock_auth_admin,
        monkeypatch: pytest.MonkeyPatch,
        both_configured: None,
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        install_transport(monkeypatch, handler)

        failed = await client.get(
            "/admin/api/observability/backups", headers=ADMIN_HEADERS
        )
        assert failed.status_code == 502

        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/ready")).status_code == 200
        services = await client.get("/admin/api/services", headers=ADMIN_HEADERS)
        assert services.status_code == 200
        assert len(services.json()) >= 3

    @pytest.mark.asyncio
    async def test_the_shared_http_client_is_not_used(
        self,
        app: FastAPI,
        client: AsyncClient,
        mock_auth_admin,
        monkeypatch: pytest.MonkeyPatch,
        prometheus_configured: None,
    ):
        """The monitoring call must not borrow the proxy connection pool."""
        from src.api.admin import observability

        seen = []
        real_factory = observability.create_observability_client

        def factory(
            transport: Optional[httpx.AsyncBaseTransport] = None,
        ) -> httpx.AsyncClient:
            built = real_factory(
                transport=httpx.MockTransport(
                    recorded_backend(query=load_fixture("prometheus_query_empty"))
                )
            )
            seen.append(built)
            return built

        monkeypatch.setattr(observability, "create_observability_client", factory)

        response = await client.get(
            "/admin/api/observability/backups", headers=ADMIN_HEADERS
        )
        assert response.status_code == 200
        assert len(seen) == 1
        assert seen[0] is not app.state.http_client
        assert seen[0].is_closed
