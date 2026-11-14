"""Shared forms and steps for campus switch and corelink workflows."""

from typing import TypeAlias, cast

from orchestrator.core.types import SubscriptionLifecycle
from orchestrator.core.workflow import step

from pydantic_forms.types import State
from pydantic_forms.validators import Choice
from services import cnaas_settings, netbox
from settings import settings
from workflows.shared import subscriptions_by_product_type

CAMPUS_ROLES = {"core": "Core", "dist": "Distribution", "access": "Access"}


def juniper_type_selector() -> type[Choice]:
    types = {str(t.id): t.model for t in netbox.get_device_types() if t.manufacturer.slug == "juniper"}
    return cast(type[Choice], Choice("JuniperTypeEnum", zip(types.keys(), types.items())))


RoleChoice: TypeAlias = cast(type[Choice], Choice("CampusRoleEnum", zip(CAMPUS_ROLES.keys(), CAMPUS_ROLES.items())))


def switch_selector(enum: str = "SwitchEnum", active_only: bool = False) -> type[Choice]:
    lifecycles = [SubscriptionLifecycle.ACTIVE]
    if not active_only:
        lifecycles.append(SubscriptionLifecycle.PROVISIONING)
    subs = sorted(subscriptions_by_product_type("Switch", lifecycles), key=lambda s: s.description)
    choices = {str(s.subscription_id): s.description for s in subs}
    return cast(type[Choice], Choice(enum, zip(choices.keys(), choices.items())))


def free_interface_selector(device_name: str, enum: str) -> type[Choice]:
    device = netbox.get_device(name=device_name)
    free = [
        i.name
        for i in netbox.get_interfaces(device_id=device.id)
        if i.type.value != "lag"
        and not i.mgmt_only
        and i.cable is None
        and i.lag is None
        and not i.name.startswith(("irb", "lo", "me", "em", "vme"))
    ]
    return cast(type[Choice], Choice(enum, zip(free, free)))


def campus_site():
    site = netbox.get_site(slug=settings.CAMPUS_SITE_SLUG)
    if site is None:
        raise ValueError(f"NetBox site '{settings.CAMPUS_SITE_SLUG}' missing, run task_bootstrap_campus first")
    return site


@step("Regenerate CNaaS settings from NetBox")
def regenerate_cnaas_settings(subscription_description: str | None = None) -> State:
    return cnaas_settings.regenerate(subscription_description or "workflow")
