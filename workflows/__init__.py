# Copyright 2019-2023 SURF.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from orchestrator.core.workflows import LazyWorkflowInstance

LazyWorkflowInstance("workflows.node.create_node", "create_node")
LazyWorkflowInstance("workflows.node.modify_node", "modify_node")
LazyWorkflowInstance("workflows.node.modify_sync_ports", "modify_sync_ports")
LazyWorkflowInstance("workflows.node.terminate_node", "terminate_node")
LazyWorkflowInstance("workflows.node.validate_node", "validate_node")


LazyWorkflowInstance("workflows.port.create_port", "create_port")
LazyWorkflowInstance("workflows.port.modify_port", "modify_port")
LazyWorkflowInstance("workflows.port.terminate_port", "terminate_port")
LazyWorkflowInstance("workflows.port.validate_port", "validate_port")


LazyWorkflowInstance("workflows.core_link.create_core_link", "create_core_link")
LazyWorkflowInstance("workflows.core_link.modify_core_link", "modify_core_link")
LazyWorkflowInstance("workflows.core_link.terminate_core_link", "terminate_core_link")
LazyWorkflowInstance("workflows.core_link.validate_core_link", "validate_core_link")


LazyWorkflowInstance("workflows.l2vpn.create_l2vpn", "create_l2vpn")
LazyWorkflowInstance("workflows.l2vpn.modify_l2vpn", "modify_l2vpn")
LazyWorkflowInstance("workflows.l2vpn.terminate_l2vpn", "terminate_l2vpn")
LazyWorkflowInstance("workflows.l2vpn.validate_l2vpn", "validate_l2vpn")
LazyWorkflowInstance("workflows.l2vpn.modify_l2vpn", "reconcile_l2vpn")


LazyWorkflowInstance("workflows.nsistp.create_nsistp", "create_nsistp")
LazyWorkflowInstance("workflows.nsistp.modify_nsistp", "modify_nsistp")
LazyWorkflowInstance("workflows.nsistp.terminate_nsistp", "terminate_nsistp")
LazyWorkflowInstance("workflows.nsistp.validate_nsistp", "validate_nsistp")


LazyWorkflowInstance("workflows.nsip2p.create_nsip2p", "create_nsip2p")
LazyWorkflowInstance("workflows.nsip2p.modify_nsip2p", "modify_nsip2p")
LazyWorkflowInstance("workflows.nsip2p.terminate_nsip2p", "terminate_nsip2p")
LazyWorkflowInstance("workflows.nsip2p.validate_nsip2p", "validate_nsip2p")


LazyWorkflowInstance("workflows.tasks.bootstrap_netbox", "task_bootstrap_netbox")
LazyWorkflowInstance("workflows.tasks.wipe_netbox", "task_wipe_netbox")
LazyWorkflowInstance("workflows.tasks.showcase", "task_showcase")


LazyWorkflowInstance("workflows.switch.create_switch", "create_switch")
LazyWorkflowInstance("workflows.switch.ztp_switch", "ztp_switch")
LazyWorkflowInstance("workflows.switch.modify_switch_sync", "modify_switch_sync")
LazyWorkflowInstance("workflows.switch.terminate_switch", "terminate_switch")
LazyWorkflowInstance("workflows.switch.validate_switch", "validate_switch")

LazyWorkflowInstance("workflows.corelink.create_corelink", "create_corelink")
LazyWorkflowInstance("workflows.corelink.modify_corelink", "modify_corelink")
LazyWorkflowInstance("workflows.corelink.terminate_corelink", "terminate_corelink")
LazyWorkflowInstance("workflows.corelink.validate_corelink", "validate_corelink")

LazyWorkflowInstance("workflows.tasks.bootstrap_campus", "task_bootstrap_campus")
LazyWorkflowInstance("workflows.tasks.bootstrap_campus", "task_regenerate_cnaas_settings")

# Campus switches live in PROVISIONING until ZTP finishes: allow ZTP and removal in that state.
from orchestrator.core.services.subscriptions import WF_USABLE_MAP  # noqa: E402

WF_USABLE_MAP.update(
    {
        "ztp_switch": ["provisioning"],
        "terminate_switch": ["provisioning", "active"],
    }
)
