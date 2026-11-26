"""Client for SUNET CNaaS-NMS (https://github.com/SUNET/cnaas-nms).

CNaaS-NMS owns the device state machine (DHCP_BOOT -> DISCOVERED -> INIT -> MANAGED), renders the Junos
config from the templates repo + settings repo and pushes it with NAPALM. The orchestrator never edits
CNaaS settings by hand: they are generated from NetBox (see ``services.cnaas_settings``).

When ``settings.CNAAS_ENABLED`` is False every call returns canned data, so workflows, the NMS GUI and
tests run without a CNaaS instance.
"""

import time
from pathlib import Path
from typing import Any

import httpx
import structlog

from settings import settings

logger = structlog.get_logger(__name__)

# CNaaS device_type per campus role. In the L2-campus design the core pair hosts the management gateway
# (CNaaS "DIST" with a mgmtdomain) and every switch below it is a CNaaS "ACCESS" device whose uplinks
# are detected by LLDP during init.
CNAAS_DEVICE_TYPE = {"core": "DIST", "dist": "ACCESS", "access": "ACCESS"}

JOB_DONE = {"FINISHED"}
JOB_FAILED = {"EXCEPTION", "ABORTED"}


class CnaasError(Exception):
    pass


def _token() -> str:
    if settings.CNAAS_TOKEN:
        return settings.CNAAS_TOKEN
    path = Path(settings.CNAAS_TOKEN_FILE)
    return path.read_text().strip() if path.exists() else ""


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=settings.CNAAS_API_URL,
        headers={"Authorization": f"Bearer {_token()}"},
        verify=settings.CNAAS_VERIFY_TLS,
        timeout=60,
    )


def _request(method: str, path: str, **kwargs: Any) -> dict:
    with _client() as client:
        response = client.request(method, path, **kwargs)
    try:
        body = response.json()
    except ValueError:
        body = {"status": "error", "data": response.text}
    if response.status_code >= 400 or body.get("status") == "error":
        raise CnaasError(f"CNaaS {method} {path} failed ({response.status_code}): {body.get('data') or body}")
    return body


def enabled() -> bool:
    return settings.CNAAS_ENABLED


# --- devices ---------------------------------------------------------------------------------------


def get_devices(**filters: str) -> list[dict]:
    if not enabled():
        return []
    params = {f"filter[{k}]": v for k, v in filters.items()}
    params["per_page"] = "1000"
    return _request("GET", "/devices", params=params)["data"]["devices"]


def get_device(hostname: str) -> dict | None:
    if not enabled():
        return None
    try:
        devices = _request("GET", f"/device/{hostname}")["data"]["devices"]
    except CnaasError:
        return None
    return devices[0] if devices else None


def get_device_by_id(device_id: int) -> dict | None:
    if not enabled():
        return None
    devices = _request("GET", f"/device/{device_id}")["data"]["devices"]
    return devices[0] if devices else None


def add_device(hostname: str, device_type: str, serial: str | None, management_ip: str | None, state: str) -> int:
    """Register a device, e.g. a pre-staged core switch (state MANAGED) or a PRE_CONFIGURED placeholder."""
    if not enabled():
        return 0
    payload = {
        "hostname": hostname,
        "device_type": device_type,
        "platform": "junos",
        "state": state,
        "serial": serial,
        "management_ip": management_ip,
    }
    body = _request("POST", "/device", json={k: v for k, v in payload.items() if v is not None})
    return body["data"]["added_device"]["id"]


def update_device(device_id: int, **fields: Any) -> None:
    if enabled():
        _request("PUT", f"/device/{device_id}", json=fields)


def delete_device(device_id: int, factory_default: bool = False) -> int | None:
    if not enabled():
        return None
    body = _request("DELETE", f"/device/{device_id}", json={"factory_default": factory_default})
    return body.get("job_id")


def discovered_devices() -> list[dict]:
    """Devices that booted the generic ZTP config and wait for an operator to init them."""
    if not enabled():
        return [
            {
                "id": 9001,
                "hostname": "mac-0c8610aabb01",
                "ztp_mac": "0c8610aabb01",
                "dhcp_ip": "10.100.2.21",
                "serial": "MOCKSERIAL01",
                "model": "EX4400-48T",
                "platform": "junos",
                "state": "DISCOVERED",
            }
        ]
    return get_devices(state="DISCOVERED")


# --- init / sync -----------------------------------------------------------------------------------


def init_check(device_id: int, hostname: str, device_type: str) -> dict:
    """Dry-run of device_init: verifies LLDP neighbours/uplinks against the expected topology."""
    if not enabled():
        return {"compatible": True, "linknets": [], "neighbors": [], "mock": True}
    body = _request("POST", f"/device_initcheck/{device_id}", json={"hostname": hostname, "device_type": device_type})
    return body["data"]


def init_device(device_id: int, hostname: str, device_type: str) -> int | None:
    if not enabled():
        return None
    body = _request("POST", f"/device_init/{device_id}", json={"hostname": hostname, "device_type": device_type})
    return body["job_id"]


def syncto(hostname: str, dry_run: bool = True, comment: str | None = None, force: bool = False) -> int | None:
    if not enabled():
        return None
    payload: dict[str, Any] = {"hostname": hostname, "dry_run": dry_run, "force": force}
    if comment:
        payload["comment"] = comment
    return _request("POST", "/device_syncto", json=payload)["job_id"]


def update_facts(hostname: str) -> int | None:
    if not enabled():
        return None
    return _request("POST", "/device_update_facts", json={"hostname": hostname})["job_id"]


# --- mgmt domains ------------------------------------------------------------------------------------


def get_mgmtdomains() -> list[dict]:
    if not enabled():
        return []
    return _request("GET", "/mgmtdomains")["data"]["mgmtdomains"]


def add_mgmtdomain(device_a: str, device_b: str, vlan: int, ipv4_gw: str, description: str) -> int:
    if not enabled():
        return 0
    body = _request(
        "POST",
        "/mgmtdomains",
        json={"device_a": device_a, "device_b": device_b, "vlan": vlan, "ipv4_gw": ipv4_gw, "description": description},
    )
    return body["data"]["added_mgmtdomain"]["id"]


def delete_mgmtdomain(mgmtdomain_id: int) -> None:
    if enabled():
        _request("DELETE", f"/mgmtdomain/{mgmtdomain_id}")


# --- repositories / jobs -----------------------------------------------------------------------------


def refresh_repository(repo: str) -> str:
    """repo is 'settings' or 'templates'. CNaaS pulls the git remote and validates the result."""
    if not enabled():
        return "mock: repository not refreshed"
    return str(_request("PUT", f"/repository/{repo}", json={"action": "refresh"})["data"])


def get_job(job_id: int) -> dict:
    if not enabled():
        return {"id": job_id, "status": "FINISHED", "result": {"mock": True}}
    return _request("GET", f"/job/{job_id}")["data"]["jobs"][0]


def get_jobs(limit: int = 25) -> list[dict]:
    if not enabled():
        return []
    params = {"per_page": str(limit), "sort": "-id"}
    return _request("GET", "/jobs", params=params)["data"]["jobs"]


def wait_for_job(job_id: int | None, timeout: int | None = None, interval: int = 5) -> dict:
    """Block until a CNaaS job finishes. Raises CnaasError on failure or timeout."""
    if job_id is None:
        return {"status": "FINISHED", "result": {"mock": True}}
    deadline = time.monotonic() + (timeout or settings.CNAAS_JOB_TIMEOUT)
    while time.monotonic() < deadline:
        job = get_job(job_id)
        status = job.get("status")
        if status in JOB_DONE:
            return job
        if status in JOB_FAILED:
            raise CnaasError(f"CNaaS job {job_id} {status}: {job.get('exception') or job.get('result')}")
        time.sleep(interval)
    raise CnaasError(f"CNaaS job {job_id} did not finish within {timeout or settings.CNAAS_JOB_TIMEOUT}s")


def wait_for_state(hostname: str, state: str, timeout: int = 600, interval: int = 10) -> dict:
    if not enabled():
        return {"hostname": hostname, "state": state}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        device = get_device(hostname)
        if device and device.get("state") == state:
            return device
        time.sleep(interval)
    raise CnaasError(f"{hostname} did not reach state {state} within {timeout}s")


def job_diff(job: dict) -> str:
    """Extract the config diff(s) from a syncto job result."""
    result = job.get("result") or {}
    devices = result.get("devices", {}) if isinstance(result, dict) else {}
    diffs = []
    for hostname, data in devices.items():
        for task in data.get("job_tasks", []):
            if task.get("diff"):
                diffs.append(f"# {hostname}\n{task['diff']}")
    return "\n".join(diffs)


# --- live data for the NMS ---------------------------------------------------------------------------


def live_interfaces(hostname: str) -> list[dict]:
    if not enabled():
        return [
            {"name": f"ge-0/0/{i}", "enabled": True, "up": i % 3 != 0, "description": "", "speed": 1000}
            for i in range(8)
        ]
    data = _request("GET", f"/device/{hostname}/interface_status")["data"]["interface_status"]
    return [
        {
            "name": name,
            "enabled": v.get("is_enabled"),
            "up": v.get("is_up"),
            "description": v.get("description", ""),
            "speed": v.get("speed"),
        }
        for name, v in sorted(data.items())
    ]


def lldp_neighbors(hostname: str) -> dict:
    if not enabled():
        return {}
    return _request("GET", f"/device/{hostname}/lldp_neighbors")["data"].get("lldp_neighbors", {})


def update_interfaces(hostname: str) -> int | None:
    """Re-detect interfaces/uplinks of an ACCESS device (after a corelink change)."""
    if not enabled():
        return None
    return _request("POST", "/device_update_interfaces", json={"hostname": hostname, "replace": False})["job_id"]
