"""Read-mostly BFF for the NMS pages in the WFO UI, mounted at /api/nms.

Fans out to the WFO DB (subscriptions), NetBox (inventory) and CNaaS-NMS (device state, jobs, live data),
so the NetBox token and CNaaS JWT stay server side.
"""

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from orchestrator.core.domain.base import SubscriptionModel
from orchestrator.core.security import authenticate
from orchestrator.core.services.processes import start_process
from orchestrator.core.types import SubscriptionLifecycle
from starlette.concurrency import run_in_threadpool

from products.product_types.switch import SwitchProvisioning
from services import cnaas_client, netbox
from workflows.shared import subscriptions_by_product_type

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/nms", tags=["nms"], dependencies=[Depends(authenticate)])

LIFECYCLES = [SubscriptionLifecycle.PROVISIONING, SubscriptionLifecycle.ACTIVE]


def _switch_subscriptions() -> list[SwitchProvisioning]:
    result = []
    for s in subscriptions_by_product_type("Switch", LIFECYCLES):
        try:
            result.append(SubscriptionModel.from_subscription(s.subscription_id))
        except Exception as e:  # one broken subscription must not take the NMS down
            logger.warning(
                "Skipping unloadable switch subscription", subscription_id=str(s.subscription_id), error=str(e)
            )
    return result


def _cnaas_by_hostname() -> dict[str, dict]:
    try:
        return {d["hostname"]: d for d in cnaas_client.get_devices()}
    except cnaas_client.CnaasError:
        return {}


def _row(sub: SwitchProvisioning, nb_device, cnaas: dict | None) -> dict[str, Any]:
    block = sub.switch
    return {
        "subscription_id": str(sub.subscription_id),
        "hostname": block.switch_name,
        "role": block.role,
        "site": nb_device.site.name if nb_device else None,
        "mgmt_ip": str(nb_device.primary_ip4).split("/")[0] if nb_device and nb_device.primary_ip4 else None,
        "serial": block.serial,
        "model": nb_device.device_type.model if nb_device else None,
        "netbox_id": block.ims_id,
        "netbox_status": nb_device.status.value if nb_device else None,
        "cnaas_id": cnaas.get("id") if cnaas else None,
        "cnaas_state": cnaas.get("state") if cnaas else ("MOCK" if not cnaas_client.enabled() else None),
        "cnaas_synchronized": cnaas.get("synchronized") if cnaas else None,
        "os_version": (cnaas or {}).get("os_version"),
    }


def _switches() -> list[dict]:
    subs = _switch_subscriptions()
    nb = {d.id: d for d in netbox.get_devices(id=[s.switch.ims_id for s in subs])} if subs else {}
    cnaas = _cnaas_by_hostname()
    return sorted(
        (_row(s, nb.get(s.switch.ims_id), cnaas.get(s.switch.switch_name)) for s in subs), key=lambda r: r["hostname"]
    )


def _switch_detail(hostname: str) -> dict:
    sub = next((s for s in _switch_subscriptions() if s.switch.switch_name == hostname), None)
    if sub is None:
        raise HTTPException(404, f"No switch subscription for {hostname}")
    device = netbox.get_device(id=sub.switch.ims_id)
    cnaas = cnaas_client.get_device(hostname)
    corelinks = []
    for s in subscriptions_by_product_type("Corelink", LIFECYCLES):
        link = SubscriptionModel.from_subscription(s.subscription_id).corelink
        a, b = link.aggregates
        if hostname in (a.switch.switch_name, b.switch.switch_name):
            corelinks.append(
                {
                    "subscription_id": str(s.subscription_id),
                    "description": s.description,
                    "a_side": f"{a.switch.switch_name}:{a.lag_name}",
                    "b_side": f"{b.switch.switch_name}:{b.lag_name}",
                    "members": len(link.members),
                }
            )
    netbox_data = None
    if device:
        netbox_data = {
            "id": device.id,
            "name": device.name,
            "status": device.status.value,
            "role": device.role.name,
            "site": device.site.name,
            "model": device.device_type.model,
            "serial": device.serial,
            "primary_ip4": str(device.primary_ip4) if device.primary_ip4 else None,
            "custom_fields": dict(device.custom_fields),
        }
    return {
        "wfo": {
            "subscription_id": str(sub.subscription_id),
            "description": sub.description,
            "status": str(sub.status),
            **sub.switch.model_dump(exclude={"title"}),
        },
        "netbox": netbox_data,
        "cnaas": cnaas,
        "corelinks": corelinks,
    }


def _discovered() -> list[dict]:
    planned = {
        s.switch.serial: str(s.subscription_id)
        for s in _switch_subscriptions()
        if s.switch.serial and s.status == SubscriptionLifecycle.PROVISIONING
    }
    return [
        {
            "cnaas_id": d["id"],
            "hostname": d.get("hostname"),
            "ztp_mac": d.get("ztp_mac"),
            "dhcp_ip": d.get("dhcp_ip"),
            "serial": d.get("serial"),
            "model": d.get("model"),
            "platform": d.get("platform"),
            "state": d.get("state"),
            "matched_subscription_id": planned.get(d.get("serial")),
        }
        for d in cnaas_client.discovered_devices()
    ]


@router.get("/switches")
async def switches() -> list[dict]:
    return await run_in_threadpool(_switches)


@router.get("/switches/{hostname}")
async def switch_detail(hostname: str) -> dict:
    return await run_in_threadpool(_switch_detail, hostname)


@router.post("/switches/{hostname}/live")
async def switch_live(hostname: str) -> dict:
    from datetime import datetime, timezone

    def fetch() -> dict:
        try:
            return {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "interfaces": cnaas_client.live_interfaces(hostname),
                "facts": cnaas_client.get_device(hostname) or {},
            }
        except cnaas_client.CnaasError as e:
            raise HTTPException(502, str(e))

    return await run_in_threadpool(fetch)


@router.get("/discovered")
async def discovered() -> list[dict]:
    return await run_in_threadpool(_discovered)


@router.post("/discovered/{cnaas_id}/ztp")
async def start_ztp(cnaas_id: int) -> dict:
    match = next((d for d in await run_in_threadpool(_discovered) if d["cnaas_id"] == cnaas_id), None)
    if not match or not match["matched_subscription_id"]:
        raise HTTPException(409, "Discovered device does not match a planned switch serial")
    process_id = await run_in_threadpool(
        start_process,
        "ztp_switch",
        [{"subscription_id": match["matched_subscription_id"]}, {"adopt_existing": False, "cnaas_device_id": cnaas_id}],
        "nms",
    )
    return {"process_id": str(process_id)}


@router.get("/jobs")
async def jobs(limit: int = 25) -> list[dict]:
    rows = await run_in_threadpool(cnaas_client.get_jobs, limit)
    keys = ("id", "function_name", "status", "start_time", "finish_time", "comment", "ticket_ref")
    return [{k: j.get(k) for k in keys} for j in rows]
