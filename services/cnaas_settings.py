"""Generate the CNaaS-NMS settings repository from NetBox.

NetBox is the single source of truth. CNaaS reads its settings from a git repository, so this module
renders that repository from NetBox and commits it to a bare repo (served to CNaaS by the ``cnaas-git``
container), then asks CNaaS to refresh.

Mapping NetBox -> CNaaS settings:

=================================================  ============================================
NetBox                                             CNaaS settings file
=================================================  ============================================
config context ``cnaas_base_system`` (site)       global/base_system.yml (ntp, dns, syslog, users...)
VLANs in VLAN group ``campus``                     global/vxlans.yml (vlan_id/vlan_name, vni=10000+vid)
devices with role core|dist|access                 global/groups.yml (CORE / DIST / ACCESS groups)
core switch LAG + member interfaces                devices/<core>/interfaces.yml (downlink + aggregate_id)
=================================================  ============================================
"""

import re
import tempfile
from pathlib import Path

import structlog
import yaml
from dulwich import porcelain
from dulwich.repo import Repo

from services import cnaas_client, netbox
from settings import settings

logger = structlog.get_logger(__name__)

CAMPUS_ROLES = ("core", "dist", "access")


def _dump(data: dict) -> str:
    return "---\n" + yaml.safe_dump(data, sort_keys=False, default_flow_style=False)


def _site():
    return netbox.get_site(slug=settings.CAMPUS_SITE_SLUG)


def base_system() -> dict:
    """Merge config contexts named/keyed ``cnaas_base_system`` that apply to the campus site."""
    site = _site()
    data: dict = {}
    if site is None:
        return data
    for ctx in netbox.api.extras.config_contexts.filter(site_id=site.id):
        data.update(ctx.data.get("cnaas_base_system", {}))
    return data


def vxlans() -> dict:
    result: dict = {}
    for vlan in netbox.get_vlans(group=settings.CAMPUS_SITE_SLUG):
        name = re.sub(r"[^A-Za-z0-9_]", "_", vlan.name)
        result[name] = {
            "vni": 10000 + vlan.vid,
            "vlan_id": vlan.vid,
            "vlan_name": name[:32],
            "groups": ["ALL"],
        }
    return {"vxlans": result}


def campus_devices() -> list:
    return [d for d in netbox.get_devices(role=list(CAMPUS_ROLES), site=settings.CAMPUS_SITE_SLUG)]


def groups(devices: list) -> dict:
    by_role: dict[str, list[str]] = {role: [] for role in CAMPUS_ROLES}
    for device in devices:
        by_role[device.role.slug].append(device.name)
    return {
        "groups": [
            {"group": {"name": "ALL", "device_filter": {"hostname": ".*"}}},
            *({"group": {"name": role.upper(), "devices": sorted(names)}} for role, names in by_role.items() if names),
        ]
    }


def core_interfaces(device) -> dict:
    """Interfaces.yml for a core switch (CNaaS DIST): every LAG member is a downlink with its aggregate id."""
    interfaces = []
    lags = {i.id: i for i in netbox.get_interfaces(device_id=device.id, type="lag")}
    for iface in netbox.get_interfaces(device_id=device.id):
        if iface.lag and iface.lag.id in lags:
            ae = lags[iface.lag.id].name  # ae<N>
            interfaces.append(
                {
                    "name": iface.name,
                    "ifclass": "downlink",
                    "aggregate_id": int(ae.removeprefix("ae")),
                    "cli_append_str": f'description "{lags[iface.lag.id].description or ae}"',
                }
            )
    return {"interfaces": sorted(interfaces, key=lambda i: i["name"])}


def render() -> dict[str, str]:
    """Render the full settings repository as {relative path: file content}."""
    devices = campus_devices()
    files = {
        "global/base_system.yml": _dump(base_system()),
        "global/vxlans.yml": _dump(vxlans()),
        "global/groups.yml": _dump(groups(devices)),
        "global/routing.yml": _dump({}),
        "fabric/base_system.yml": _dump({}),
        "core/base_system.yml": _dump({}),
        "dist/base_system.yml": _dump({}),
        "access/base_system.yml": _dump({}),
    }
    for device in devices:
        if device.role.slug == "core":
            files[f"devices/{device.name}/interfaces.yml"] = _dump(core_interfaces(device))
    return files


def commit(files: dict[str, str], message: str) -> str | None:
    """Replace the content of the bare settings repo with ``files``. Returns the new commit id or None."""
    bare = Path(settings.CNAAS_SETTINGS_REPO)
    if not bare.exists():
        logger.warning("Settings repo missing, skipping commit", path=str(bare))
        return None
    with tempfile.TemporaryDirectory() as tmp:
        porcelain.clone(str(bare), tmp, checkout=True)
        work = Path(tmp)
        for old in [p for p in work.rglob("*") if p.is_file() and ".git" not in p.parts]:
            old.unlink()
        for rel, content in files.items():
            target = work / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        porcelain.add(tmp, paths=[str(work / rel) for rel in files])
        repo = Repo(tmp)
        tracked = {p.decode() for p in repo.open_index()}
        removed = [p for p in tracked if p not in files]
        if removed:
            porcelain.remove(tmp, paths=[str(work / p) for p in removed], cached=True)
        status = porcelain.status(tmp)
        if not any(status.staged.values()):
            return None
        sha = porcelain.commit(
            tmp,
            message=message.encode(),
            author=b"Wired Orchestrator <wfo@campus.local>",
            committer=b"Wired Orchestrator <wfo@campus.local>",
        )
        porcelain.push(tmp, str(bare), b"refs/heads/master")
        return sha.decode()


def regenerate(reason: str) -> dict:
    """Render from NetBox, commit and refresh CNaaS. Safe to call from any workflow step."""
    files = render()
    sha = commit(files, f"wfo: {reason}")
    refresh = cnaas_client.refresh_repository("settings") if sha else "unchanged"
    return {"settings_commit": sha, "settings_files": sorted(files), "settings_refresh": refresh}
