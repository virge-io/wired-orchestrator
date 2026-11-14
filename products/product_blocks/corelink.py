"""SURF-style corelink: two aggregate sides (ae / NetBox LAG) and 1..8 link members (port pairs + cable).

MVP transport is an L2 LACP trunk (mgmt + service VLANs), no IPs on the ae.
"""

from typing import Annotated

from annotated_types import Len
from orchestrator.core.domain.base import ProductBlockModel
from orchestrator.core.types import SI, SubscriptionLifecycle
from pydantic import computed_field

from products.product_blocks.switch import SwitchBlock, SwitchBlockInactive, SwitchBlockProvisioning


class CorelinkAggregateBlockInactive(ProductBlockModel, product_block_name="CorelinkAggregate"):
    switch: SwitchBlockInactive
    lag_name: str | None = None  # ae<N>
    lag_ims_id: int | None = None


class CorelinkAggregateBlockProvisioning(
    CorelinkAggregateBlockInactive, lifecycle=[SubscriptionLifecycle.PROVISIONING]
):
    switch: SwitchBlockProvisioning
    lag_name: str
    lag_ims_id: int | None = None


class CorelinkAggregateBlock(CorelinkAggregateBlockProvisioning, lifecycle=[SubscriptionLifecycle.ACTIVE]):
    switch: SwitchBlock
    lag_name: str
    lag_ims_id: int


class CorelinkMemberBlockInactive(ProductBlockModel, product_block_name="CorelinkMember"):
    a_port_name: str | None = None
    b_port_name: str | None = None
    a_port_ims_id: int | None = None
    b_port_ims_id: int | None = None
    cable_ims_id: int | None = None


class CorelinkMemberBlockProvisioning(CorelinkMemberBlockInactive, lifecycle=[SubscriptionLifecycle.PROVISIONING]):
    a_port_name: str
    b_port_name: str
    a_port_ims_id: int | None = None
    b_port_ims_id: int | None = None
    cable_ims_id: int | None = None


class CorelinkMemberBlock(CorelinkMemberBlockProvisioning, lifecycle=[SubscriptionLifecycle.ACTIVE]):
    a_port_name: str
    b_port_name: str
    a_port_ims_id: int
    b_port_ims_id: int
    cable_ims_id: int


Aggregates = Annotated[list[SI], Len(min_length=2, max_length=2)]
Members = Annotated[list[SI], Len(min_length=1, max_length=8)]


class CorelinkBlockInactive(ProductBlockModel, product_block_name="Corelink"):
    aggregates: Aggregates[CorelinkAggregateBlockInactive]
    members: Members[CorelinkMemberBlockInactive]
    under_maintenance: bool | None = None


class CorelinkBlockProvisioning(CorelinkBlockInactive, lifecycle=[SubscriptionLifecycle.PROVISIONING]):
    aggregates: Aggregates[CorelinkAggregateBlockProvisioning]
    members: Members[CorelinkMemberBlockProvisioning]
    under_maintenance: bool

    @computed_field  # type: ignore[misc]
    @property
    def title(self) -> str:
        a, b = self.aggregates
        return f"corelink {a.switch.switch_name}:{a.lag_name} - {b.switch.switch_name}:{b.lag_name}"


class CorelinkBlock(CorelinkBlockProvisioning, lifecycle=[SubscriptionLifecycle.ACTIVE]):
    aggregates: Aggregates[CorelinkAggregateBlock]
    members: Members[CorelinkMemberBlock]
    under_maintenance: bool
