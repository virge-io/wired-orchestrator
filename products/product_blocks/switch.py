"""Campus switch (Juniper) managed through NetBox + CNaaS-NMS."""

from orchestrator.core.domain.base import ProductBlockModel
from orchestrator.core.types import SubscriptionLifecycle
from pydantic import computed_field


class SwitchBlockInactive(ProductBlockModel, product_block_name="Switch"):
    switch_name: str | None = None
    role: str | None = None  # core | dist | access
    site_id: int | None = None
    type_id: int | None = None
    serial: str | None = None
    ims_id: int | None = None  # NetBox device id
    mgmt_ipam_id: int | None = None
    loopback_ipam_id: int | None = None
    cnaas_device_id: int | None = None
    cnaas_device_type: str | None = None  # DIST | ACCESS


class SwitchBlockProvisioning(SwitchBlockInactive, lifecycle=[SubscriptionLifecycle.PROVISIONING]):
    switch_name: str
    role: str
    site_id: int
    type_id: int
    serial: str | None = None
    ims_id: int
    mgmt_ipam_id: int | None = None  # access/dist: CNaaS assigns it from the mgmtdomain during init
    loopback_ipam_id: int | None = None
    cnaas_device_id: int | None = None
    cnaas_device_type: str

    @computed_field  # type: ignore[misc]
    @property
    def title(self) -> str:
        return f"{self.role} switch {self.switch_name}"


class SwitchBlock(SwitchBlockProvisioning, lifecycle=[SubscriptionLifecycle.ACTIVE]):
    # orchestrator-core persists the fields declared on the concrete lifecycle class: redeclare them all.
    switch_name: str
    role: str
    site_id: int
    type_id: int
    serial: str
    ims_id: int
    mgmt_ipam_id: int
    loopback_ipam_id: int | None = None
    cnaas_device_id: int
    cnaas_device_type: str
