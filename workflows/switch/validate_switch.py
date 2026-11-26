"""Validate a campus switch: NetBox state, CNaaS state and configuration drift (syncto dry run)."""

from orchestrator.core.workflow import StepList, begin, step
from orchestrator.core.workflows.utils import validate_workflow

from products.product_types.switch import Switch
from pydantic_forms.types import State
from services import cnaas_client, netbox
from workflows.switch.modify_switch_sync import syncto_dry_run


@step("Validate switch in NetBox")
def validate_netbox(subscription: Switch) -> State:
    device = netbox.get_device(id=subscription.switch.ims_id)
    errors = []
    if device is None:
        raise ValueError(f"NetBox device {subscription.switch.ims_id} missing")
    if device.name != subscription.switch.switch_name:
        errors.append(f"name {device.name} != {subscription.switch.switch_name}")
    if device.status.value != "active":
        errors.append(f"status {device.status.value}")
    if device.serial != subscription.switch.serial:
        errors.append(f"serial {device.serial} != {subscription.switch.serial}")
    if errors:
        raise ValueError("NetBox mismatch: " + "; ".join(errors))
    return {"netbox": "ok"}


@step("Validate switch in CNaaS")
def validate_cnaas(subscription: Switch) -> State:
    if not cnaas_client.enabled():
        return {"cnaas": "mock"}
    device = cnaas_client.get_device(subscription.switch.switch_name)
    if device is None or device["state"] != "MANAGED":
        raise ValueError(f"CNaaS device state: {device and device['state']}")
    return {"cnaas": {"state": device["state"], "synchronized": device.get("synchronized")}}


@step("Check configuration drift")
def check_drift(subscription: Switch) -> State:
    diffs = syncto_dry_run([subscription.switch.switch_name], "validate")
    drift = {h: d for h, d in diffs.items() if d}
    if drift:
        raise ValueError(f"Configuration drift detected:\n{drift}")
    return {"drift": "none"}


@validate_workflow()
def validate_switch() -> StepList:
    return begin >> validate_netbox >> validate_cnaas >> check_drift
