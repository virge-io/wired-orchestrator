"""Bootstrap NetBox for a campus managed through CNaaS-NMS (idempotent).

Creates: Juniper manufacturer + device types (with interface templates), platform ``junos``, roles
core/dist/access, the campus site, management/loopback prefixes, VLAN group + management VLAN,
custom fields ``subscription_id`` / ``os_version`` and a ``cnaas_base_system`` config context.
"""

import structlog
from orchestrator.core.workflow import StepList, done, init, step
from orchestrator.core.workflows.utils import task

from pydantic_forms.types import State
from services import cnaas_settings, netbox
from settings import settings

logger = structlog.get_logger(__name__)

# model -> list of (name pattern, count, type); a trimmed copy of netbox-community/devicetype-library
JUNIPER_TYPES = {
    "EX4400-48T": [
        ("ge-0/0/{}", 48, "1000base-t"),
        ("xe-0/2/{}", 4, "10gbase-x-sfpp"),
        ("et-0/1/{}", 2, "100gbase-x-qsfp28"),
    ],
    "EX4100-48P": [("ge-0/0/{}", 48, "1000base-t"), ("xe-0/2/{}", 4, "10gbase-x-sfpp")],
    "QFX5120-48Y": [("xe-0/0/{}", 48, "25gbase-x-sfp28"), ("et-0/0/{}", 8, "100gbase-x-qsfp28")],
    "vJunos-switch": [("ge-0/0/{}", 10, "1000base-t")],
}
ROLES = {"core": "Core", "dist": "Distribution", "access": "Access"}
ROLE_COLORS = {"core": "f44336", "dist": "2196f3", "access": "4caf50"}

DEFAULT_BASE_SYSTEM = {
    "ntp_servers": [{"host": "pool.ntp.org"}],
    "dns_servers": [{"host": "9.9.9.9"}],
    "syslog_servers": [],
    "organization_name": "Campus",
    "domain_name": "campus.local",
}


def get_or_create(endpoint, lookup: dict, **extra):
    obj = endpoint.get(**lookup)
    return obj or endpoint.create(**lookup, **extra)


@step("Create Juniper device types")
def create_device_types() -> State:
    api = netbox.api
    juniper = get_or_create(api.dcim.manufacturers, {"slug": "juniper"}, name="Juniper")
    get_or_create(api.dcim.platforms, {"slug": "junos"}, name="Junos", manufacturer=juniper.id)
    created = []
    for model, templates in JUNIPER_TYPES.items():
        slug = model.lower()
        dtype = api.dcim.device_types.get(slug=slug)
        if dtype:
            continue
        dtype = api.dcim.device_types.create(manufacturer=juniper.id, model=model, slug=slug, u_height=1)
        api.dcim.interface_templates.create(
            [
                {"device_type": dtype.id, "name": pattern.format(i), "type": itype}
                for pattern, count, itype in templates
                for i in range(count)
            ]
        )
        created.append(model)
    return {"device_types_created": created}


@step("Create roles, site, prefixes, VLANs and custom fields")
def create_campus_objects() -> State:
    api = netbox.api
    for slug, name in ROLES.items():
        get_or_create(api.dcim.device_roles, {"slug": slug}, name=name, color=ROLE_COLORS[slug])
    site = get_or_create(api.dcim.sites, {"slug": settings.CAMPUS_SITE_SLUG}, name="Campus", status="active")
    for prefix, role_desc in (
        (settings.CAMPUS_MGMT_PREFIX, "management"),
        (settings.CAMPUS_LOOPBACK_PREFIX, "loopback"),
    ):
        get_or_create(
            api.ipam.prefixes,
            {"prefix": prefix},
            description=f"campus {role_desc}",
            status="active",
            scope_type="dcim.site",
            scope_id=site.id,
        )
    group = get_or_create(
        api.ipam.vlan_groups,
        {"slug": settings.CAMPUS_SITE_SLUG},
        name="campus",
        scope_type="dcim.site",
        scope_id=site.id,
    )
    get_or_create(
        api.ipam.vlans, {"group_id": group.id, "vid": settings.CAMPUS_MGMT_VLAN}, name="mgmt", status="active"
    )
    for name, label in (("subscription_id", "WFO subscription"), ("os_version", "OS version")):
        get_or_create(
            api.extras.custom_fields,
            {"name": name},
            label=label,
            type="text",
            object_types=["dcim.device"],
        )
    get_or_create(
        api.extras.config_contexts,
        {"name": "cnaas-base-system-campus"},
        sites=[site.id],
        data={"cnaas_base_system": DEFAULT_BASE_SYSTEM},
        weight=1000,
    )
    return {"site_id": site.id}


@step("Regenerate CNaaS settings")
def regenerate() -> State:
    return cnaas_settings.regenerate("bootstrap campus")


@task()
def task_bootstrap_campus() -> StepList:
    return init >> create_device_types >> create_campus_objects >> regenerate >> done


@task()
def task_regenerate_cnaas_settings() -> StepList:
    return init >> regenerate >> done
