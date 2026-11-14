"""Remove a campus switch from CNaaS (optionally factory-default it) and NetBox."""

from typing import Annotated

from orchestrator.core.forms import FormPage
from orchestrator.core.workflow import StepList, begin, step
from orchestrator.core.workflows.utils import terminate_workflow
from pydantic import Field

from products.product_types.switch import SwitchProvisioning
from pydantic_forms.types import InputForm, State, UUIDstr
from pydantic_forms.validators import DisplaySubscription
from services import cnaas_client, netbox
from workflows.switch.shared import regenerate_cnaas_settings


def terminate_initial_input_form_generator(subscription_id: UUIDstr) -> InputForm:
    SubscriptionId = Annotated[DisplaySubscription, Field(subscription_id)]

    class TerminateForm(FormPage):
        subscription_id: SubscriptionId
        factory_default: bool = False

    return TerminateForm


@step("Remove device from CNaaS")
def remove_from_cnaas(subscription: SwitchProvisioning, factory_default: bool) -> State:
    device = cnaas_client.get_device(subscription.switch.switch_name)
    if device:
        cnaas_client.wait_for_job(cnaas_client.delete_device(device["id"], factory_default=factory_default))
    return {"cnaas_removed": bool(device)}


@step("Delete device from NetBox")
def remove_from_netbox(subscription: SwitchProvisioning) -> State:
    for ip_id in {subscription.switch.mgmt_ipam_id, subscription.switch.loopback_ipam_id} - {None}:
        netbox.delete_ip_address(id=ip_id)
    netbox.delete_device(id=subscription.switch.ims_id)
    return {}


@terminate_workflow(initial_input_form=terminate_initial_input_form_generator)
def terminate_switch() -> StepList:
    return begin >> remove_from_cnaas >> remove_from_netbox >> regenerate_cnaas_settings
