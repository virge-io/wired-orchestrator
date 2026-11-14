"""Terminate a corelink: remove cables, members and LAGs from NetBox, then push config to both ends."""

from typing import Annotated

from orchestrator.core.forms import FormPage
from orchestrator.core.workflow import StepList, begin, step
from orchestrator.core.workflows.utils import terminate_workflow
from pydantic import Field

from products.product_types.corelink import Corelink
from pydantic_forms.types import InputForm, State, UUIDstr
from pydantic_forms.validators import DisplaySubscription
from services import netbox
from workflows.corelink.shared import managed_hostnames, refresh_access_uplinks, remove_member, syncto_commit
from workflows.switch.shared import regenerate_cnaas_settings


def terminate_initial_input_form_generator(subscription_id: UUIDstr) -> InputForm:
    SubscriptionId = Annotated[DisplaySubscription, Field(subscription_id)]

    class TerminateForm(FormPage):
        subscription_id: SubscriptionId

    return TerminateForm


@step("Remove corelink from NetBox")
def remove_from_netbox(subscription: Corelink) -> State:
    for member in subscription.corelink.members:
        remove_member(member)
    for agg in subscription.corelink.aggregates:
        if agg.lag_ims_id and (lag := netbox.get_interface(id=agg.lag_ims_id)):
            lag.delete()
    return {}


@step("Push config to both ends")
def push(subscription: Corelink) -> State:
    refresh = refresh_access_uplinks(subscription.corelink.aggregates)
    return {
        "uplink_refresh": refresh,
        "sync_result": syncto_commit(managed_hostnames(subscription.corelink.aggregates), "terminate corelink"),
    }


@terminate_workflow(initial_input_form=terminate_initial_input_form_generator)
def terminate_corelink() -> StepList:
    return begin >> remove_from_netbox >> regenerate_cnaas_settings >> push
