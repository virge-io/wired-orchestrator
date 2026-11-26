"""Zero Touch Provisioning of a planned campus switch.

Phase 1 happens without the orchestrator: a factory-default Junos switch DHCP-boots on the ZTP VLAN, CNaaS
dhcpd hands out option 43 pointing at ``templates/junos/dhcp-init.j2``, the switch commits that generic
bootstrap config and CNaaS discovers it (state DISCOVERED).

Phase 2 is this workflow, started from the NMS "Discovered" list (or the subscription page):
serial check -> device_initcheck (LLDP vs topology) -> device_init (hostname, device type, mgmt VLAN/IP)
-> wait until MANAGED -> NetBox active + mgmt IP + facts -> subscription ACTIVE.

``adopt_existing`` handles brownfield/pre-staged switches (typically the first core pair): the device is
registered in CNaaS directly as MANAGED on its NetBox loopback/mgmt address instead of going through ZTP.
"""

from ipaddress import IPv4Interface, IPv4Network

from orchestrator.core.forms import FormPage
from orchestrator.core.types import SubscriptionLifecycle
from orchestrator.core.workflow import StepList, begin, conditional, step
from orchestrator.core.workflows.steps import set_status
from orchestrator.core.workflows.utils import modify_workflow
from pydantic import ConfigDict

from products.product_types.switch import Switch, SwitchProvisioning
from pydantic_forms.types import FormGenerator, State, UUIDstr
from services import cnaas_client, netbox
from settings import settings
from workflows.switch.shared import regenerate_cnaas_settings


def initial_input_form_generator(subscription_id: UUIDstr) -> FormGenerator:
    subscription = SwitchProvisioning.from_subscription(subscription_id)
    discovered = cnaas_client.discovered_devices()
    match = next(
        (d for d in discovered if subscription.switch.serial and d.get("serial") == subscription.switch.serial), None
    )

    class ZtpForm(FormPage):
        model_config = ConfigDict(title=f"ZTP {subscription.switch.switch_name}")

        adopt_existing: bool = False
        cnaas_device_id: int | None = match["id"] if match else None

    user_input = yield ZtpForm
    data = user_input.model_dump()
    if not data["adopt_existing"] and data["cnaas_device_id"] is None:
        raise ValueError("Select the discovered CNaaS device id, or choose adopt_existing")
    return data


ztp = conditional(lambda state: not state["adopt_existing"])
adopt = conditional(lambda state: state["adopt_existing"])
is_core = conditional(lambda state: state["subscription"]["switch"]["role"] == "core")


@step("Check discovered device matches the planned switch")
def check_discovered_device(subscription: SwitchProvisioning, cnaas_device_id: int) -> State:
    device = cnaas_client.get_device_by_id(cnaas_device_id) or {
        "state": "DISCOVERED",
        "serial": subscription.switch.serial,
    }
    if device["state"] != "DISCOVERED":
        raise ValueError(f"CNaaS device {cnaas_device_id} is {device['state']}, expected DISCOVERED")
    serial = device.get("serial")
    if subscription.switch.serial and serial and serial != subscription.switch.serial:
        raise ValueError(f"Serial mismatch: planned {subscription.switch.serial}, discovered {serial}")
    if serial and not subscription.switch.serial:
        subscription.switch.serial = serial
    return {"subscription": subscription, "discovered_device": device}


@step("CNaaS init check (LLDP neighbours)")
def init_check(subscription: SwitchProvisioning, cnaas_device_id: int) -> State:
    result = cnaas_client.init_check(
        cnaas_device_id, subscription.switch.switch_name, subscription.switch.cnaas_device_type
    )
    if not result.get("compatible", False):
        raise ValueError(f"Init check failed, fix cabling/NetBox and retry: {result}")
    return {"init_check": result}


@step("CNaaS device init")
def init_device(subscription: SwitchProvisioning, cnaas_device_id: int) -> State:
    job_id = cnaas_client.init_device(
        cnaas_device_id, subscription.switch.switch_name, subscription.switch.cnaas_device_type
    )
    job = cnaas_client.wait_for_job(job_id)
    device = cnaas_client.wait_for_state(subscription.switch.switch_name, "MANAGED")
    subscription.switch.cnaas_device_id = cnaas_device_id
    return {"subscription": subscription, "init_job": job_id, "init_result": job.get("result"), "cnaas_device": device}


@step("Register pre-staged switch in CNaaS as MANAGED")
def adopt_device(subscription: SwitchProvisioning) -> State:
    block = subscription.switch
    mgmt_ip = None
    if block.loopback_ipam_id:
        mgmt_ip = str(IPv4Interface(netbox.get_ip_address(id=block.loopback_ipam_id).address).ip)
    existing = cnaas_client.get_device(block.switch_name)
    device_id = (
        existing["id"]
        if existing
        else cnaas_client.add_device(block.switch_name, block.cnaas_device_type, block.serial, mgmt_ip, "MANAGED")
    )
    cnaas_client.wait_for_job(cnaas_client.update_facts(block.switch_name))
    block.cnaas_device_id = device_id
    return {"subscription": subscription, "cnaas_device": cnaas_client.get_device(block.switch_name)}


@step("Record management IP and facts in NetBox")
def update_netbox(subscription: SwitchProvisioning, cnaas_device: dict | None = None) -> State:
    block = subscription.switch
    cnaas_device = cnaas_device or {}
    device = netbox.get_device(id=block.ims_id)
    mgmt_ip = cnaas_device.get("management_ip")
    if block.role == "core" and block.loopback_ipam_id:
        block.mgmt_ipam_id = block.loopback_ipam_id
    else:
        prefixlen = IPv4Network(settings.CAMPUS_MGMT_PREFIX).prefixlen
        irb = netbox.create(
            netbox.InterfacePayload(
                device=block.ims_id, name=f"irb.{settings.CAMPUS_MGMT_VLAN}", type="virtual", enabled=True
            )
        )
        address = f"{mgmt_ip}/{prefixlen}" if mgmt_ip else None
        if address is None:  # mock mode: allocate the next free address so NetBox stays consistent
            prefix = netbox.get_ip_prefix(prefix=settings.CAMPUS_MGMT_PREFIX)
            ip = prefix.available_ips.create({"assigned_object_type": "dcim.interface", "assigned_object_id": irb})
        else:
            ip = netbox.api.ipam.ip_addresses.create(
                address=address, assigned_object_type="dcim.interface", assigned_object_id=irb
            )
        ip.dns_name = block.switch_name
        ip.description = f"mgmt {block.switch_name} (assigned by CNaaS)"
        ip.save()
        block.mgmt_ipam_id = ip.id
    device.status = "active"
    device.primary_ip4 = block.mgmt_ipam_id
    if block.serial:
        device.serial = block.serial
    device.custom_fields["os_version"] = cnaas_device.get("os_version")
    device.save()
    return {"subscription": subscription}


@step("Pair core switches in a CNaaS mgmtdomain")
def ensure_mgmtdomain(subscription: SwitchProvisioning) -> State:
    """Both core switches together host the management VLAN gateway that access switches init into."""
    if cnaas_client.get_mgmtdomains():
        return {"mgmtdomain": "already present"}
    peers = [
        d["hostname"]
        for d in cnaas_client.get_devices(device_type="DIST", state="MANAGED")
        if d["hostname"] != subscription.switch.switch_name
    ]
    if not peers and cnaas_client.enabled():
        return {"mgmtdomain": "waiting for second core switch"}
    network = IPv4Network(settings.CAMPUS_MGMT_PREFIX)
    gw = f"{next(network.hosts())}/{network.prefixlen}"
    peer = peers[0] if peers else "mock-core"
    mgmtdomain_id = cnaas_client.add_mgmtdomain(
        peer, subscription.switch.switch_name, settings.CAMPUS_MGMT_VLAN, gw, "campus management"
    )
    return {"mgmtdomain": mgmtdomain_id}


@step("Activate subscription")
def activate(subscription: SwitchProvisioning) -> State:
    return {"subscription": Switch.from_other_lifecycle(subscription, SubscriptionLifecycle.ACTIVE)}


@modify_workflow(initial_input_form=initial_input_form_generator)
def ztp_switch() -> StepList:
    return (
        begin
        >> ztp(check_discovered_device)
        >> ztp(init_check)
        >> ztp(init_device)
        >> adopt(adopt_device)
        >> update_netbox
        >> is_core(ensure_mgmtdomain)
        >> activate
        >> set_status(SubscriptionLifecycle.ACTIVE)
        >> regenerate_cnaas_settings
    )
