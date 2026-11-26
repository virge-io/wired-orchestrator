from orchestrator.core.domain.base import SubscriptionModel
from orchestrator.core.types import SubscriptionLifecycle

from products.product_blocks.corelink import CorelinkBlock, CorelinkBlockInactive, CorelinkBlockProvisioning


class CorelinkInactive(SubscriptionModel, is_base=True):
    corelink: CorelinkBlockInactive


class CorelinkProvisioning(CorelinkInactive, lifecycle=[SubscriptionLifecycle.PROVISIONING]):
    corelink: CorelinkBlockProvisioning


class Corelink(CorelinkProvisioning, lifecycle=[SubscriptionLifecycle.ACTIVE]):
    corelink: CorelinkBlock
