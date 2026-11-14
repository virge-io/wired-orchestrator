"""Add a new campus switch.

NetBox: planned device (role, type, serial, subscription_id) + loopback IP for core switches.
CNaaS: the settings repo is regenerated so the new hostname/groups exist before the switch boots.
The subscription stays PROVISIONING until ``ztp_switch`` brings the device to MANAGED.
"""

from orchestrator.core.forms import FormPage
from orchestrator.core.types import SubscriptionLifecycle
from orchestrator.core.workflow import StepList, begin, conditional, step
from orchestrator.core.workflows.steps import store_process_subscription
from orchestrator.core.workflows.utils import create_workflow
from pydantic import ConfigDict, field_validator

from products.product_types.switch import SwitchInactive, SwitchProvisioning
from pydantic_forms.types import FormGenerator, State, UUIDstr
from pydantic_forms.validators import Label
from services import netbox
from services.cnaas_client import CNAAS_DEVICE_TYPE
from settings import settings
from workflows.shared import create_summary_form, customer_selector
from workflows.switch.shared import RoleChoice, campus_site, juniper_type_selector, regenerate_cnaas_settings


def initial_input_form_generator(product_name: str) -> FormGenerator:
    TypeChoice = juniper_type_selector()

    class CreateSwitchForm(FormPage):
        model_config = ConfigDict(title=product_name)

        customer_id: customer_selector()  # type: ignore[valid-type]
        switch_settings: Label
        switch_name: str
        role: RoleChoice  # type: ignore[valid-type]
        type_id: TypeChoice  # type: ignore[valid-type]
        serial: str | None = None

        @field_validator("switch_name")
        @classmethod
        def valid_hostname(cls, v: str) -> str:
            if not v.replace("-", "").isalnum() or len(v) > 63:
                raise ValueError("Hostname may only contain letters, digits and dashes")
            if netbox.get_device(name=v):
                raise ValueError(f"Device {v} already exists in NetBox")
            return v.lower()

    user_input = yield CreateSwitchForm
    data = user_input.model_dump()
    yield from create_summary_form(data, product_name, ["switch_name", "role", "type_id", "serial"])
    return data


@step("Construct subscription model")
def construct_switch_model(
    product: UUIDstr, customer_id: UUIDstr, switch_name: str, role: str, type_id: int, serial: str | None
) -> State:
    subscription = SwitchInactive.from_product_id(
        product_id=product, customer_id=customer_id, status=SubscriptionLifecycle.INITIAL
    )
    block = subscription.switch
    block.switch_name = switch_name
    block.role = str(role)
    block.type_id = int(type_id)
    block.site_id = campus_site().id
    block.serial = serial or None
    block.cnaas_device_type = CNAAS_DEVICE_TYPE[str(role)]
    subscription.description = f"{role} switch {switch_name}"
    return {
        "subscription": subscription,
        "subscription_id": subscription.subscription_id,
        "subscription_description": subscription.description,
    }


@step("Create planned device in NetBox")
def create_device_in_netbox(subscription: SwitchInactive) -> State:
    block = subscription.switch
    device = netbox.api.dcim.devices.create(
        name=block.switch_name,
        role={"slug": block.role},
        device_type=block.type_id,
        site=block.site_id,
        status="planned",
        serial=block.serial or "",
        platform={"slug": "junos"},
        custom_fields={"subscription_id": str(subscription.subscription_id)},
    )
    block.ims_id = device.id
    return {"subscription": subscription, "netbox_device_id": device.id}


@step("Reserve loopback address in NetBox")
def reserve_loopback(subscription: SwitchInactive) -> State:
    block = subscription.switch
    lo = netbox.create(netbox.InterfacePayload(device=block.ims_id, name="lo0", type="virtual", enabled=True))
    prefix = netbox.get_ip_prefix(prefix=settings.CAMPUS_LOOPBACK_PREFIX)
    netbox.skip_network_address(prefix)
    ip = prefix.available_ips.create(
        {
            "description": f"loopback {block.switch_name}",
            "assigned_object_type": "dcim.interface",
            "assigned_object_id": lo,
            "dns_name": block.switch_name,
        }
    )
    block.loopback_ipam_id = ip.id
    return {"subscription": subscription, "loopback_ip": str(ip.address)}


is_core = conditional(lambda state: state["role"] == "core")


@step("Mark subscription provisioning")
def to_provisioning(subscription: SwitchInactive) -> State:
    return {"subscription": SwitchProvisioning.from_other_lifecycle(subscription, SubscriptionLifecycle.PROVISIONING)}


@create_workflow(initial_input_form=initial_input_form_generator, status=SubscriptionLifecycle.PROVISIONING)
def create_switch() -> StepList:
    return (
        begin
        >> construct_switch_model
        >> store_process_subscription()
        >> create_device_in_netbox
        >> is_core(reserve_loopback)
        >> to_provisioning
        >> regenerate_cnaas_settings
    )
