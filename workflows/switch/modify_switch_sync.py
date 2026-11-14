"""Push the CNaaS-rendered config to a switch: regenerate settings, dry-run diff, confirm, commit."""

from orchestrator.core.forms import FormPage
from orchestrator.core.workflow import StepList, begin, inputstep, step
from orchestrator.core.workflows.utils import modify_workflow

from products.product_types.switch import Switch
from pydantic_forms.types import FormGenerator, State, UUIDstr
from pydantic_forms.validators import Label
from services import cnaas_client
from workflows.switch.shared import regenerate_cnaas_settings


def initial_input_form_generator(subscription_id: UUIDstr) -> FormGenerator:
    class SyncForm(FormPage):
        comment: str | None = None

    user_input = yield SyncForm
    return user_input.model_dump()


def syncto_dry_run(hostnames: list[str], comment: str | None) -> dict:
    diffs = {}
    for hostname in hostnames:
        job = cnaas_client.wait_for_job(cnaas_client.syncto(hostname, dry_run=True, comment=comment))
        diffs[hostname] = cnaas_client.job_diff(job)
    return diffs


def syncto_commit(hostnames: list[str], comment: str | None) -> dict:
    results = {}
    for hostname in hostnames:
        job_id = cnaas_client.syncto(hostname, dry_run=False, comment=comment)
        results[hostname] = cnaas_client.wait_for_job(job_id).get("status")
    return results


@step("Dry-run config sync")
def dry_run(subscription: Switch, comment: str | None = None) -> State:
    return {"config_diff": syncto_dry_run([subscription.switch.switch_name], comment)}


@inputstep("Confirm config diff", assignee="SYSTEM")
def confirm_diff(config_diff: dict) -> FormGenerator:
    text = "\n".join(f"{h}:\n{d or '(no changes)'}" for h, d in config_diff.items())

    class ConfirmForm(FormPage):
        diff: Label = text  # type: ignore[assignment]
        confirm: bool = False

    user_input = yield ConfirmForm
    if not user_input.confirm:
        raise ValueError("Config push not confirmed")
    return {}


@step("Commit config sync (commit confirmed)")
def commit(subscription: Switch, comment: str | None = None) -> State:
    return {"sync_result": syncto_commit([subscription.switch.switch_name], comment)}


@modify_workflow(initial_input_form=initial_input_form_generator)
def modify_switch_sync() -> StepList:
    return begin >> regenerate_cnaas_settings >> dry_run >> confirm_diff >> commit
