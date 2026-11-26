"""Create a corelink between two campus switches (typically core <-> dist).

NetBox: aeN LAG on both switches, members attached with ``lag=``, one cable per member.
CNaaS: settings regenerated (core side gets ``downlink`` interfaces with aggregate_id), access side
re-detects its uplinks, then a dry-run diff is shown and committed on both ends.
"""

from orchestrator.core.domain.base import SubscriptionModel
from orchestrator.core.forms import FormPage
from orchestrator.core.types import SubscriptionLifecycle
from orchestrator.core.workflow import StepList, begin, step
from orchestrator.core.workflows.steps import store_process_subscription
from orchestrator.core.workflows.utils import create_workflow
from pydantic import ConfigDict, model_validator

from products.product_blocks.corelink import CorelinkMemberBlockInactive
from products.product_types.corelink import CorelinkInactive, CorelinkProvisioning
from pydantic_forms.types import FormGenerator, State, UUIDstr
from pydantic_forms.validators import choice_list
from workflows.corelink.shared import (
    add_member,
    create_lag,
    managed_hostnames,
    next_ae,
    refresh_access_uplinks,
    syncto_commit,
    syncto_dry_run,
)
from workflows.shared import create_summary_form, customer_selector
from workflows.switch.modify_switch_sync import confirm_diff
from workflows.switch.shared import free_interface_selector, regenerate_cnaas_settings, switch_selector


def initial_input_form_generator(product_name: str) -> FormGenerator:
    class SelectSwitches(FormPage):
        model_config = ConfigDict(title=product_name)

        customer_id: customer_selector()  # type: ignore[valid-type]
        side_a: switch_selector("SideAEnum")  # type: ignore[valid-type]
        side_b: switch_selector("SideBEnum")  # type: ignore[valid-type]

        @model_validator(mode="after")
        def different_switches(self) -> "SelectSwitches":
            if self.side_a == self.side_b:
                raise ValueError("Side A and side B must be different switches")
            return self

    switches = yield SelectSwitches
    a = SubscriptionModel.from_subscription(switches.side_a)
    b = SubscriptionModel.from_subscription(switches.side_b)

    class SelectMembers(FormPage):
        model_config = ConfigDict(title=f"Members {a.switch.switch_name} - {b.switch.switch_name}")

        a_ports: choice_list(  # type: ignore[valid-type]
            free_interface_selector(a.switch.switch_name, "APortsEnum"), min_items=1, max_items=8, unique_items=True
        )
        b_ports: choice_list(  # type: ignore[valid-type]
            free_interface_selector(b.switch.switch_name, "BPortsEnum"), min_items=1, max_items=8, unique_items=True
        )

        @model_validator(mode="after")
        def same_count(self) -> "SelectMembers":
            if len(self.a_ports) != len(self.b_ports):
                raise ValueError("Select the same number of ports on both sides (paired in order)")
            return self

    members = yield SelectMembers
    data = switches.model_dump() | members.model_dump()
    yield from create_summary_form(data, product_name, ["a_ports", "b_ports"])
    return data


@step("Construct subscription model")
def construct_corelink_model(
    product: UUIDstr, customer_id: UUIDstr, side_a: UUIDstr, side_b: UUIDstr, a_ports: list[str], b_ports: list[str]
) -> State:
    subscription = CorelinkInactive.from_product_id(
        product_id=product, customer_id=customer_id, status=SubscriptionLifecycle.INITIAL
    )
    link = subscription.corelink
    link.under_maintenance = False
    for agg, switch_id in zip(link.aggregates, (side_a, side_b)):
        agg.switch = SubscriptionModel.from_subscription(switch_id).switch
        agg.lag_name = next_ae(agg.switch.ims_id)
    link.members = [
        CorelinkMemberBlockInactive.new(
            subscription_id=subscription.subscription_id, a_port_name=str(a), b_port_name=str(b)
        )
        for a, b in zip(a_ports, b_ports)
    ]
    subscription = CorelinkProvisioning.from_other_lifecycle(subscription, SubscriptionLifecycle.PROVISIONING)
    subscription.description = subscription.corelink.title
    return {
        "subscription": subscription,
        "subscription_id": subscription.subscription_id,
        "subscription_description": subscription.description,
    }


@step("Create LAGs, members and cables in NetBox")
def create_in_netbox(subscription: CorelinkProvisioning) -> State:
    a, b = subscription.corelink.aggregates
    for agg, peer in ((a, b), (b, a)):
        create_lag(agg, f"corelink to {peer.switch.switch_name}:{peer.lag_name}")
    for member in subscription.corelink.members:
        add_member(a, b, member)
    return {"subscription": subscription}


@step("Re-detect access uplinks in CNaaS")
def refresh_uplinks(subscription: CorelinkProvisioning) -> State:
    return {"uplink_refresh": refresh_access_uplinks(subscription.corelink.aggregates)}


@step("Dry-run config sync on both ends")
def dry_run(subscription: CorelinkProvisioning) -> State:
    hostnames = managed_hostnames(subscription.corelink.aggregates)
    return {"sync_hostnames": hostnames, "config_diff": syncto_dry_run(hostnames, subscription.description)}


@step("Commit config sync on both ends")
def commit(subscription: CorelinkProvisioning, sync_hostnames: list[str]) -> State:
    return {"sync_result": syncto_commit(sync_hostnames, subscription.description)}


@create_workflow(initial_input_form=initial_input_form_generator)
def create_corelink() -> StepList:
    return (
        begin
        >> construct_corelink_model
        >> store_process_subscription()
        >> create_in_netbox
        >> regenerate_cnaas_settings
        >> refresh_uplinks
        >> dry_run
        >> confirm_diff
        >> commit
    )
