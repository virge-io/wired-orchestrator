"""Add or remove corelink members (1..8), or toggle maintenance."""

from orchestrator.core.forms import FormPage
from orchestrator.core.workflow import StepList, begin, step
from orchestrator.core.workflows.utils import modify_workflow
from pydantic import model_validator

from products.product_blocks.corelink import CorelinkMemberBlockInactive
from products.product_types.corelink import Corelink
from pydantic_forms.types import FormGenerator, State, UUIDstr
from pydantic_forms.validators import Choice, choice_list
from workflows.corelink.shared import (
    add_member,
    managed_hostnames,
    refresh_access_uplinks,
    remove_member,
    syncto_commit,
    syncto_dry_run,
)
from workflows.switch.modify_switch_sync import confirm_diff
from workflows.switch.shared import free_interface_selector, regenerate_cnaas_settings


def initial_input_form_generator(subscription_id: UUIDstr) -> FormGenerator:
    subscription = Corelink.from_subscription(subscription_id)
    a, b = subscription.corelink.aggregates
    current = {
        str(m.subscription_instance_id): f"{m.a_port_name} <-> {m.b_port_name}" for m in subscription.corelink.members
    }
    count = len(current)

    class ModifyCorelinkForm(FormPage):
        under_maintenance: bool = subscription.corelink.under_maintenance
        remove_members: choice_list(  # type: ignore[valid-type]
            Choice("RemoveEnum", zip(current.keys(), current.items())), min_items=0, max_items=count
        ) = []
        add_a_ports: choice_list(  # type: ignore[valid-type]
            free_interface_selector(a.switch.switch_name, "AddAEnum"), min_items=0, max_items=8, unique_items=True
        ) = []
        add_b_ports: choice_list(  # type: ignore[valid-type]
            free_interface_selector(b.switch.switch_name, "AddBEnum"), min_items=0, max_items=8, unique_items=True
        ) = []

        @model_validator(mode="after")
        def check_counts(self) -> "ModifyCorelinkForm":
            if len(self.add_a_ports) != len(self.add_b_ports):
                raise ValueError("Add the same number of ports on both sides")
            total = count - len(self.remove_members) + len(self.add_a_ports)
            if not 1 <= total <= 8:
                raise ValueError(f"A corelink needs 1..8 members, this change results in {total}")
            return self

    user_input = yield ModifyCorelinkForm
    return user_input.model_dump()


@step("Update members in NetBox")
def update_members(
    subscription: Corelink,
    under_maintenance: bool,
    remove_members: list[str],
    add_a_ports: list[str],
    add_b_ports: list[str],
) -> State:
    link = subscription.corelink
    a, b = link.aggregates
    link.under_maintenance = under_maintenance
    removed = [m for m in link.members if str(m.subscription_instance_id) in set(map(str, remove_members))]
    for member in removed:
        remove_member(member)
    link.members = [m for m in link.members if m not in removed]
    for a_port, b_port in zip(add_a_ports, add_b_ports):
        member = CorelinkMemberBlockInactive.new(
            subscription_id=subscription.subscription_id, a_port_name=str(a_port), b_port_name=str(b_port)
        )
        add_member(a, b, member)
        link.members.append(member)
    return {"subscription": subscription, "members_removed": len(removed), "members_added": len(add_a_ports)}


@step("Re-detect access uplinks in CNaaS")
def refresh_uplinks(subscription: Corelink) -> State:
    return {"uplink_refresh": refresh_access_uplinks(subscription.corelink.aggregates)}


@step("Dry-run config sync on both ends")
def dry_run(subscription: Corelink) -> State:
    hostnames = managed_hostnames(subscription.corelink.aggregates)
    return {"sync_hostnames": hostnames, "config_diff": syncto_dry_run(hostnames, subscription.description)}


@step("Commit config sync on both ends")
def commit(subscription: Corelink, sync_hostnames: list[str]) -> State:
    return {"sync_result": syncto_commit(sync_hostnames, subscription.description)}


@modify_workflow(initial_input_form=initial_input_form_generator)
def modify_corelink() -> StepList:
    return begin >> update_members >> regenerate_cnaas_settings >> refresh_uplinks >> dry_run >> confirm_diff >> commit
