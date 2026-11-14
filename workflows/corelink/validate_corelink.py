"""Validate a corelink against NetBox (LAGs, member lag= refs, cables) and LLDP as seen by CNaaS."""

from orchestrator.core.workflow import StepList, begin, step
from orchestrator.core.workflows.utils import validate_workflow

from products.product_types.corelink import Corelink
from pydantic_forms.types import State
from services import cnaas_client, netbox


@step("Validate corelink in NetBox")
def validate_netbox(subscription: Corelink) -> State:
    errors = []
    a, b = subscription.corelink.aggregates
    for member in subscription.corelink.members:
        for if_id, agg in ((member.a_port_ims_id, a), (member.b_port_ims_id, b)):
            iface = netbox.get_interface(id=if_id)
            if iface is None or iface.lag is None or iface.lag.id != agg.lag_ims_id:
                errors.append(f"{agg.switch.switch_name} interface {if_id} not member of {agg.lag_name}")
        if not netbox.get_cable(id=member.cable_ims_id):
            errors.append(f"cable {member.cable_ims_id} missing")
    if errors:
        raise ValueError("; ".join(errors))
    return {"netbox": "ok"}


@step("Validate LLDP neighbours")
def validate_lldp(subscription: Corelink) -> State:
    if not cnaas_client.enabled():
        return {"lldp": "mock"}
    a, b = subscription.corelink.aggregates
    neighbors = cnaas_client.lldp_neighbors(a.switch.switch_name)
    errors = []
    for member in subscription.corelink.members:
        seen = [n.get("hostname", "").split(".")[0] for n in neighbors.get(member.a_port_name, [])]
        if b.switch.switch_name not in seen:
            errors.append(f"{a.switch.switch_name}:{member.a_port_name} sees {seen}, expected {b.switch.switch_name}")
    if errors:
        raise ValueError("; ".join(errors))
    return {"lldp": "ok"}


@validate_workflow()
def validate_corelink() -> StepList:
    return begin >> validate_netbox >> validate_lldp
