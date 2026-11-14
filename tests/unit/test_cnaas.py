"""Unit tests for the CNaaS integration that run without NetBox/CNaaS (mock mode + fakes)."""

import subprocess
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from services import cnaas_client, cnaas_settings
from settings import settings

TEMPLATES = Path(__file__).parents[2] / "cnaas" / "templates" / "junos"


def test_mock_mode_returns_canned_data(monkeypatch):
    monkeypatch.setattr(settings, "CNAAS_ENABLED", False)
    assert cnaas_client.discovered_devices()[0]["state"] == "DISCOVERED"
    assert cnaas_client.wait_for_job(None)["status"] == "FINISHED"
    assert cnaas_client.init_check(1, "sw1", "ACCESS")["compatible"] is True
    assert cnaas_client.syncto("sw1") is None


def test_job_diff_extracts_device_diffs():
    job = {"result": {"devices": {"core1": {"job_tasks": [{"diff": "+ set foo"}, {"diff": ""}]}}}}
    assert cnaas_client.job_diff(job) == "# core1\n+ set foo"


def test_wait_for_job_raises_on_exception(monkeypatch):
    monkeypatch.setattr(settings, "CNAAS_ENABLED", True)
    monkeypatch.setattr(cnaas_client, "get_job", lambda job_id: {"status": "EXCEPTION", "exception": "boom"})
    with pytest.raises(cnaas_client.CnaasError, match="boom"):
        cnaas_client.wait_for_job(7)


def _fake_netbox(monkeypatch):
    core = NS(id=1, name="core1", role=NS(slug="core"))
    dist = NS(id=2, name="dist1", role=NS(slug="dist"))
    lag = NS(id=10, name="ae3", description="corelink to dist1:ae0", lag=None)
    members = [NS(id=11 + i, name=f"xe-0/0/{i}", lag=NS(id=10)) for i in range(2)]
    other = NS(id=20, name="xe-0/0/9", lag=None)

    def get_interfaces(device_id, type=None):
        if device_id != 1:
            return []
        return [lag] if type == "lag" else [lag, *members, other]

    nb = cnaas_settings.netbox
    monkeypatch.setattr(nb, "get_interfaces", get_interfaces)
    monkeypatch.setattr(nb, "get_vlans", lambda **kw: [NS(vid=10, name="mgmt"), NS(vid=100, name="Staff WiFi")])
    monkeypatch.setattr(cnaas_settings, "campus_devices", lambda: [core, dist])
    monkeypatch.setattr(cnaas_settings, "base_system", lambda: {"ntp_servers": [{"host": "10.0.0.1"}]})


def test_render_maps_netbox_to_cnaas_settings(monkeypatch):
    _fake_netbox(monkeypatch)
    files = cnaas_settings.render()
    interfaces = yaml.safe_load(files["devices/core1/interfaces.yml"])["interfaces"]
    assert interfaces == [
        {
            "name": "xe-0/0/0",
            "ifclass": "downlink",
            "aggregate_id": 3,
            "cli_append_str": 'description "corelink to dist1:ae0"',
        },
        {
            "name": "xe-0/0/1",
            "ifclass": "downlink",
            "aggregate_id": 3,
            "cli_append_str": 'description "corelink to dist1:ae0"',
        },
    ]
    vx = yaml.safe_load(files["global/vxlans.yml"])["vxlans"]
    assert vx["Staff_WiFi"] == {"vni": 10100, "vlan_id": 100, "vlan_name": "Staff_WiFi", "groups": ["ALL"]}
    groups = {g["group"]["name"]: g["group"] for g in yaml.safe_load(files["global/groups.yml"])["groups"]}
    assert groups["CORE"]["devices"] == ["core1"] and groups["DIST"]["devices"] == ["dist1"]
    assert "devices/dist1/interfaces.yml" not in files  # access-type devices get uplinks via LLDP


def test_commit_to_bare_repo_is_idempotent(monkeypatch, tmp_path):
    bare = tmp_path / "settings.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "master", str(bare)], check=True)
    work = tmp_path / "seed"
    subprocess.run(["git", "init", "-q", "-b", "master", str(work)], check=True)
    (work / "README").write_text("seed")
    subprocess.run(["git", "-C", str(work), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(work), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed"], check=True
    )
    subprocess.run(["git", "-C", str(work), "push", "-q", str(bare), "master"], check=True)
    monkeypatch.setattr(settings, "CNAAS_SETTINGS_REPO", str(bare))

    files = {"global/base_system.yml": "---\nntp_servers: []\n"}
    assert cnaas_settings.commit(files, "first")
    assert cnaas_settings.commit(files, "again") is None  # nothing changed
    tree = subprocess.run(
        ["git", "-C", str(bare), "ls-tree", "-r", "--name-only", "master"], capture_output=True, text=True, check=True
    ).stdout.split()
    assert tree == ["global/base_system.yml"]  # stale files removed


@pytest.mark.parametrize("entry", ["core.j2", "access.j2"])
def test_junos_templates_render(entry):
    env = Environment(loader=FileSystemLoader(TEMPLATES), undefined=StrictUndefined, extensions=["jinja2.ext.do"])
    ctx = {
        "host": "sw1",
        "mgmt_ip": "10.100.0.10",
        "mgmt_ipif": "10.100.0.10/24",
        "mgmt_vlan_id": 10,
        "mgmt_gw": "10.100.0.1",
        "domain_name": "campus.local",
        "banner_login": "",
        "TEMPLATE_SECRET_ROOT_HASH": "x",
        "TEMPLATE_SECRET_CNAAS_HASH": "y",
        "users": [],
        "dns_servers": [],
        "syslog_servers": [],
        "ntp_servers": [{"host": "10.0.0.1"}],
        "vxlans": {"staff": {"vlan_id": 100, "vlan_name": "staff"}},
        "mgmtdomains": [{"ipv4_gw": "10.100.0.1/24"}],
        "interfaces": [
            {"name": "xe-0/0/0", "ifclass": "downlink", "aggregate_id": 3, "enabled": True},
            {"name": "ge-0/0/0", "ifclass": "ACCESS_UPLINK", "data": {}},
            {"name": "ge-0/0/5", "ifclass": "ACCESS_UNTAGGED", "data": {"untagged_vlan": 100}},
        ],
    }
    config = env.get_template(entry).render(**ctx)
    assert "host-name sw1;" in config
    assert config.count("{") == config.count("}")
    assert ("ae3 {" in config) if entry == "core.j2" else ("802.3ad ae0;" in config)
