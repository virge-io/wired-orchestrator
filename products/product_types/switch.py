from orchestrator.core.domain.base import SubscriptionModel
from orchestrator.core.types import SubscriptionLifecycle

from products.product_blocks.switch import SwitchBlock, SwitchBlockInactive, SwitchBlockProvisioning


class SwitchInactive(SubscriptionModel, is_base=True):
    switch: SwitchBlockInactive


class SwitchProvisioning(SwitchInactive, lifecycle=[SubscriptionLifecycle.PROVISIONING]):
    switch: SwitchBlockProvisioning


class Switch(SwitchProvisioning, lifecycle=[SubscriptionLifecycle.ACTIVE]):
    switch: SwitchBlock
