"""NetBox + CNaaS helpers for campus corelinks (LAG + members + one cable per member)."""

from products.product_blocks.corelink import CorelinkAggregateBlockProvisioning, CorelinkMemberBlockProvisioning
from services import cnaas_client, netbox
from workflows.switch.modify_switch_sync import syncto_commit, syncto_dry_run


def next_ae(device_id: int) -> str:
    used = {
        int(i.name.removeprefix("ae"))
        for i in netbox.get_interfaces(device_id=device_id, type="lag")
        if i.name.removeprefix("ae").isdigit()
    }
    return f"ae{next(n for n in range(0, 128) if n not in used)}"


def create_lag(agg: CorelinkAggregateBlockProvisioning, description: str) -> None:
    agg.lag_ims_id = netbox.create(
        netbox.InterfacePayload(
            device=agg.switch.ims_id, name=agg.lag_name, type="lag", enabled=True, description=description
        )
    )


def interface(device_id: int, name: str):
    iface = netbox.get_interface(device_id=device_id, name=name)
    if iface is None:
        raise ValueError(f"Interface {name} not found on NetBox device {device_id}")
    return iface


def add_member(
    a: CorelinkAggregateBlockProvisioning,
    b: CorelinkAggregateBlockProvisioning,
    member: CorelinkMemberBlockProvisioning,
) -> None:
    a_if = interface(a.switch.ims_id, member.a_port_name)
    b_if = interface(b.switch.ims_id, member.b_port_name)
    for iface, agg in ((a_if, a), (b_if, b)):
        iface.lag = agg.lag_ims_id
        iface.description = f"corelink member {agg.lag_name}"
        iface.save()
    cable = netbox.api.dcim.cables.create(
        a_terminations=[{"object_type": "dcim.interface", "object_id": a_if.id}],
        b_terminations=[{"object_type": "dcim.interface", "object_id": b_if.id}],
        status="connected",
        label=f"{a.switch.switch_name}:{member.a_port_name}-{b.switch.switch_name}:{member.b_port_name}",
    )
    member.a_port_ims_id, member.b_port_ims_id, member.cable_ims_id = a_if.id, b_if.id, cable.id


def remove_member(member) -> None:
    if member.cable_ims_id:
        cable = netbox.get_cable(id=member.cable_ims_id)
        if cable:
            cable.delete()
    for if_id in (member.a_port_ims_id, member.b_port_ims_id):
        if if_id and (iface := netbox.get_interface(id=if_id)):
            iface.lag = None
            iface.description = ""
            iface.save()


def managed_hostnames(aggregates) -> list[str]:
    """Only switches CNaaS already manages get a config push; others pick the corelink up during ZTP."""
    names = []
    for agg in aggregates:
        device = cnaas_client.get_device(agg.switch.switch_name)
        if device and device.get("state") == "MANAGED" or not cnaas_client.enabled():
            names.append(agg.switch.switch_name)
    return names


def refresh_access_uplinks(aggregates) -> dict:
    jobs = {}
    for agg in aggregates:
        if agg.switch.cnaas_device_type == "ACCESS" and agg.switch.switch_name in managed_hostnames([agg]):
            jobs[agg.switch.switch_name] = cnaas_client.wait_for_job(
                cnaas_client.update_interfaces(agg.switch.switch_name)
            ).get("status")
    return jobs


__all__ = ["syncto_commit", "syncto_dry_run"]
