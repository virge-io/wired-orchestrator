"""Add campus switch (Juniper) and corelink products managed through CNaaS-NMS.

Revision ID: c1a5c0de0001
Revises: 610caa9e4286
Create Date: 2026-11-14 12:00:00.000000

"""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from orchestrator.core.migrations.helpers import (
    create,
    create_workflow,
    delete,
    delete_workflow,
    ensure_default_workflows,
)
from orchestrator.core.targets import Target

revision = "c1a5c0de0001"
down_revision = "610caa9e4286"
branch_labels = None
depends_on = None

new_products = {
    "products": {
        "switch Juniper": {
            "product_id": uuid4(),
            "product_type": "Switch",
            "description": "Campus switch (Juniper) provisioned through CNaaS-NMS",
            "tag": "SWITCH",
            "status": "active",
            "root_product_block": "Switch",
            "fixed_inputs": {},
        },
        "corelink": {
            "product_id": uuid4(),
            "product_type": "Corelink",
            "description": "Campus corelink (LACP trunk with 1..8 members)",
            "tag": "CORELINK",
            "status": "active",
            "root_product_block": "Corelink",
            "fixed_inputs": {},
        },
    },
    "product_blocks": {
        "Switch": {
            "product_block_id": uuid4(),
            "description": "campus switch",
            "tag": "SWITCH",
            "status": "active",
            "resources": {
                "switch_name": "Hostname of the switch",
                "role": "Campus role: core, dist or access",
                "site_id": "NetBox site id",
                "type_id": "NetBox device type id",
                "serial": "Chassis serial number",
                "ims_id": "NetBox device id",
                "mgmt_ipam_id": "NetBox id of the management IP address",
                "loopback_ipam_id": "NetBox id of the loopback IP address",
                "cnaas_device_id": "CNaaS-NMS device id",
                "cnaas_device_type": "CNaaS-NMS device type (DIST or ACCESS)",
            },
        },
        "CorelinkAggregate": {
            "product_block_id": uuid4(),
            "description": "one side of a corelink (ae interface)",
            "tag": "CORELINK_AGG",
            "status": "active",
            "resources": {
                "lag_name": "Aggregate interface name (aeN)",
                "lag_ims_id": "NetBox id of the LAG interface",
            },
            "depends_on_block_relations": ["Switch"],
        },
        "CorelinkMember": {
            "product_block_id": uuid4(),
            "description": "corelink member (port pair + cable)",
            "tag": "CORELINK_MEMBER",
            "status": "active",
            "resources": {
                "a_port_name": "Interface name on side A",
                "b_port_name": "Interface name on side B",
                "a_port_ims_id": "NetBox interface id on side A",
                "b_port_ims_id": "NetBox interface id on side B",
                "cable_ims_id": "NetBox cable id",
            },
        },
        "Corelink": {
            "product_block_id": uuid4(),
            "description": "campus corelink",
            "tag": "CORELINK",
            "status": "active",
            "resources": {"under_maintenance": "corelink under maintenance?"},
            "depends_on_block_relations": ["CorelinkAggregate", "CorelinkMember"],
        },
    },
    "workflows": {},
}

new_workflows = [
    {
        "name": "create_switch",
        "target": Target.CREATE,
        "is_task": False,
        "description": "Add campus switch",
        "product_type": "Switch",
    },
    {
        "name": "ztp_switch",
        "target": Target.MODIFY,
        "is_task": False,
        "description": "Zero touch provision switch",
        "product_type": "Switch",
    },
    {
        "name": "modify_switch_sync",
        "target": Target.MODIFY,
        "is_task": False,
        "description": "Push config to switch",
        "product_type": "Switch",
    },
    {
        "name": "terminate_switch",
        "target": Target.TERMINATE,
        "is_task": False,
        "description": "Remove campus switch",
        "product_type": "Switch",
    },
    {
        "name": "validate_switch",
        "target": Target.VALIDATE,
        "is_task": True,
        "description": "Validate campus switch",
        "product_type": "Switch",
    },
    {
        "name": "create_corelink",
        "target": Target.CREATE,
        "is_task": False,
        "description": "Create corelink",
        "product_type": "Corelink",
    },
    {
        "name": "modify_corelink",
        "target": Target.MODIFY,
        "is_task": False,
        "description": "Modify corelink members",
        "product_type": "Corelink",
    },
    {
        "name": "terminate_corelink",
        "target": Target.TERMINATE,
        "is_task": False,
        "description": "Terminate corelink",
        "product_type": "Corelink",
    },
    {
        "name": "validate_corelink",
        "target": Target.VALIDATE,
        "is_task": True,
        "description": "Validate corelink",
        "product_type": "Corelink",
    },
]

tasks = [
    {
        "name": "task_bootstrap_campus",
        "target": Target.SYSTEM,
        "description": "Bootstrap NetBox + CNaaS for the campus",
    },
    {
        "name": "task_regenerate_cnaas_settings",
        "target": Target.SYSTEM,
        "description": "Regenerate CNaaS settings from NetBox",
    },
]


def upgrade() -> None:
    conn = op.get_bind()
    create(conn, new_products)
    for workflow in new_workflows:
        create_workflow(conn, workflow)
    ensure_default_workflows(conn)
    for task in tasks:
        conn.execute(
            sa.text(
                """INSERT INTO workflows(name, target, description, is_task) VALUES (:name, :target, :description, true)
                   ON CONFLICT DO NOTHING"""
            ),
            task,
        )


def downgrade() -> None:
    conn = op.get_bind()
    for workflow in [*new_workflows, *tasks]:
        delete_workflow(conn, workflow["name"])
    delete(conn, new_products)
