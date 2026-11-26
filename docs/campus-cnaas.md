# Campus network with CNaaS-NMS

This guide covers the campus stack: Juniper switches managed by **SUNET CNaaS-NMS**, with **NetBox** as the source of truth and **WFO** for workflows and the NMS GUI. The stack does not use LSO.

```
NetBox (SoT) ──read──▶ WFO workflows ──REST/JWT──▶ CNaaS-NMS API ──NAPALM──▶ Junos
     ▲                     │                          ▲ settings.git  (generated from NetBox by WFO)
     └──write ids/state────┘                          │ templates.git (cnaas/templates/junos)
                     cnaas_dhcpd (option 43) + cnaas_httpd (bootstrap config)
WFO UI /nms ─▶ /api/nms (services/nms_api.py) ─▶ WFO DB + NetBox + CNaaS
```

## Start

```bash
cp .env.campus.example .env                        # set the ZTP VLAN addressing, password hashes, CNAAS_ENABLED=True
COMPOSE_PROFILES=campus docker compose build       # arm64 only: SUNET publishes amd64 images
COMPOSE_PROFILES=campus docker compose up -d
```

If you leave `CNAAS_ENABLED=False`, the orchestrator runs in mock mode and makes no calls to CNaaS. You can still walk through every workflow and the NMS pages end to end.

| Service | Purpose |
|---|---|
| `cnaas-git` | Serves `templates.git`, `etc.git` (the rendered dhcpd.conf) and `settings.git` over `git://` |
| `cnaas-jwt` | One-shot container. Creates the ES256 keypair and a token for WFO and dhcpd |
| `cnaas_api` | CNaaS-NMS API on `127.0.0.1:1443` |
| `cnaas_httpd` | Serves `templates/junos/dhcp-init.j2` to switches during ZTP on `${ZTP_HTTP_BIND}:80` |
| `cnaas_dhcpd` | ISC dhcpd with Juniper option 43. Uses host networking, because it must see the ZTP VLAN |
| `cnaas_postgres`, `cnaas_redis` | CNaaS state |

## Day-0 runbook

1. Run the **Bootstrap campus** task. It creates in NetBox the Juniper device types (with interfaces), the core/dist/access roles, the campus site, the mgmt and loopback prefixes, the mgmt VLAN, the custom fields and the `cnaas_base_system` config context. Then it generates the settings repo.
2. Edit NTP, DNS, syslog and users in the NetBox config context `cnaas-base-system-campus`, then run **Regenerate CNaaS settings**.
3. **Core pair**: run `create_switch` with role core, then `ztp_switch` with `adopt_existing` (pre-staged), or use normal ZTP. Once both cores are MANAGED, the workflow creates the CNaaS mgmtdomain, which acts as the gateway of the mgmt VLAN.
4. **Distribution/access switch**: `create_switch` with role dist or access and the chassis **serial**. This creates a planned NetBox device and a PROVISIONING subscription.
5. Cable the new switch and power it on. It DHCP-boots, fetches the bootstrap, and CNaaS marks it **DISCOVERED**.
6. In WFO UI go to **NMS → Discovered** and click **Start ZTP**. The discovered serial is matched to the planned subscription. `ztp_switch` then runs `device_initcheck` (LLDP), then `device_init`, and waits until the switch is MANAGED. It writes the mgmt IP, status and OS version to NetBox, and the subscription becomes ACTIVE.
7. **Corelink**: `create_corelink` picks switch A and B and 1 to 8 member port pairs. It creates the aeN LAGs, the members and one cable per member in NetBox, regenerates settings, shows a dry-run diff for confirmation, and then commits on both ends.

## Ownership rules

- **NetBox** owns devices, serials, racks, IPs, VLANs, LAGs and cables. Never edit CNaaS settings by hand: `services/cnaas_settings.py` overwrites them.
- **WFO** owns subscriptions and the workflow history.
- **CNaaS** owns the device state machine, config rendering and pushes, and jobs. The one exception to NetBox-first: CNaaS assigns the mgmt IP of access switches from the mgmtdomain, and `ztp_switch` records it in NetBox.

## Role mapping

| Campus role | CNaaS device_type | Template | Corelink config |
|---|---|---|---|
| core | DIST | `core.j2` | `devices/<core>/interfaces.yml`: members get `ifclass: downlink` with an `aggregate_id` |
| dist, access | ACCESS | `access.j2` | Uplinks are detected by LLDP and bundled into `ae0` |

## Known limits / to verify on real hardware

- The ACCESS-type uplink LAG and the per-interface `ifclass` names in `access.j2` follow CNaaS's interface types (`ACCESS_UPLINK`, …). Check them against a vJunos or EX lab before production.
- CNaaS init of a DIST device normally expects an EVPN fabric. Adopting the pre-staged core pair (`adopt_existing`) avoids that dependency.
- `ztp_switch` and the sync steps block a worker while they wait for CNaaS jobs (default timeout 15 minutes).
- `ztp_switch` is a MODIFY workflow that runs on a PROVISIONING subscription. Start it from NMS → Discovered or the API.
