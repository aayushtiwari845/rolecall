"""Keep asking Oracle for an Always Free Ampere A1 VM until one is free, then print its IP.

Free A1 capacity is often "out of host capacity". Oracle's advice is to retry, so this
does that politely (every few minutes, backing off when rate-limited) and stops on the
first success. It refuses to create anything that would not be free:

- only in your tenancy's home region (Always Free resources must live there),
- only up to 2 OCPUs / 12 GB of A1 in total, counting VMs you already have,
- a 50 GB boot volume (200 GB of block storage is free),
- one VM: if an instance with the same name exists, it reports it and stops.

If you have no public subnet yet it creates one (VCN, internet gateway, route, subnet)
and opens TCP 80 and 443, which are free networking resources.

Setup (once): create an API key in the Oracle console (Profile -> My profile -> API keys
-> Add API key -> Generate key pair -> download the private key), save the shown
configuration as ~/.oci/config with key_file pointing at the downloaded key.

    uv run --no-project --with oci python infra/oracle_launch.py --dry-run
    uv run --no-project --with oci python infra/oracle_launch.py
"""

from __future__ import annotations

import argparse
import random
import subprocess
import sys
import time
from pathlib import Path

import oci

SHAPE = "VM.Standard.A1.Flex"
FREE_OCPUS, FREE_MEMORY_GB = 2, 12
CAPACITY_HINTS = ("out of host capacity", "out of capacity", "capacity")


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def parse_sizes(text: str) -> list[tuple[float, float]]:
    out = []
    for part in text.split(","):
        ocpus, mem = part.split(":")
        out.append((float(ocpus), float(mem)))
    return out


def ssh_public_key(path: Path) -> str:
    pub = path.with_suffix(".pub") if path.suffix != ".pub" else path
    private = pub.with_suffix("")
    if not pub.exists():
        pub.parent.mkdir(parents=True, exist_ok=True)
        log(f"no SSH key at {pub}; generating one")
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "rolecall-vm", "-f", str(private)],
            check=True,
        )
    return pub.read_text(encoding="utf-8").strip()


def wait_available(client, getter, ocid: str) -> None:
    oci.wait_until(client, getter(ocid), "lifecycle_state", "AVAILABLE", max_wait_seconds=300)


def ensure_ports_open(vnet, security_list_id: str, ports=(80, 443)) -> None:
    sl = vnet.get_security_list(security_list_id).data
    have = {
        (r.tcp_options.destination_port_range.min, r.tcp_options.destination_port_range.max)
        for r in sl.ingress_security_rules
        if r.protocol == "6"
        and r.source == "0.0.0.0/0"
        and r.tcp_options
        and r.tcp_options.destination_port_range
    }
    missing = [p for p in ports if (p, p) not in have]
    if not missing:
        return
    rules = list(sl.ingress_security_rules) + [
        oci.core.models.IngressSecurityRule(
            protocol="6",
            source="0.0.0.0/0",
            tcp_options=oci.core.models.TcpOptions(
                destination_port_range=oci.core.models.PortRange(min=p, max=p)
            ),
            description="Rolecall web",
        )
        for p in missing
    ]
    vnet.update_security_list(
        security_list_id, oci.core.models.UpdateSecurityListDetails(ingress_security_rules=rules)
    )
    log(f"opened TCP {', '.join(map(str, missing))} in security list {sl.display_name}")


def public_subnet(vnet, compartment: str, create: bool):
    for subnet in oci.pagination.list_call_get_all_results(
        vnet.list_subnets, compartment, lifecycle_state="AVAILABLE"
    ).data:
        if not subnet.prohibit_public_ip_on_vnic:
            log(f"using public subnet {subnet.display_name}")
            return subnet
    if not create:
        return None
    log("no public subnet: creating VCN, internet gateway, route and subnet")
    m = oci.core.models
    vcn = vnet.create_vcn(
        m.CreateVcnDetails(
            compartment_id=compartment,
            cidr_blocks=["10.0.0.0/16"],
            display_name="rolecall-vcn",
            dns_label="rolecall",
        )
    ).data
    wait_available(vnet, vnet.get_vcn, vcn.id)
    igw = vnet.create_internet_gateway(
        m.CreateInternetGatewayDetails(
            compartment_id=compartment, vcn_id=vcn.id, is_enabled=True, display_name="rolecall-igw"
        )
    ).data
    wait_available(vnet, vnet.get_internet_gateway, igw.id)
    rt = vnet.get_route_table(vcn.default_route_table_id).data
    vnet.update_route_table(
        rt.id,
        m.UpdateRouteTableDetails(
            route_rules=list(rt.route_rules)
            + [
                m.RouteRule(
                    destination="0.0.0.0/0",
                    destination_type="CIDR_BLOCK",
                    network_entity_id=igw.id,
                )
            ]
        ),
    )
    subnet = vnet.create_subnet(
        m.CreateSubnetDetails(
            compartment_id=compartment,
            vcn_id=vcn.id,
            cidr_block="10.0.0.0/24",
            display_name="rolecall-public",
            dns_label="public",
            prohibit_public_ip_on_vnic=False,
        )
    ).data
    wait_available(vnet, vnet.get_subnet, subnet.id)
    return subnet


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", default="~/.oci/config")
    ap.add_argument("--profile", default="DEFAULT")
    ap.add_argument("--compartment", help="compartment OCID (default: the tenancy root)")
    ap.add_argument("--name", default="rolecall")
    ap.add_argument("--sizes", default="2:12", help="OCPU:GB tried in order, e.g. 2:12,1:6")
    ap.add_argument("--ssh-key", default="~/.ssh/rolecall.pub")
    ap.add_argument("--interval", type=int, default=180, help="seconds between rounds")
    ap.add_argument("--dry-run", action="store_true", help="check everything, launch nothing")
    args = ap.parse_args()

    try:
        config = oci.config.from_file(str(Path(args.config).expanduser()), args.profile)
        oci.config.validate_config(config)
    except (oci.exceptions.ConfigFileNotFound, oci.exceptions.InvalidConfig) as e:
        log(f"Oracle API config problem: {e}")
        log(
            "Create an API key: Oracle console -> Profile -> My profile -> API keys -> "
            "Add API key, then save the shown config as ~/.oci/config with key_file "
            "set to the downloaded private key."
        )
        return 2
    identity = oci.identity.IdentityClient(config)
    compute = oci.core.ComputeClient(config)
    vnet = oci.core.VirtualNetworkClient(config)
    tenancy = config["tenancy"]
    compartment = args.compartment or tenancy

    home = next(
        s.region_name for s in identity.list_region_subscriptions(tenancy).data if s.is_home_region
    )
    if config["region"] != home:
        log(
            f"config region {config['region']} is not your home region {home}; "
            f"Always Free VMs must be in the home region. Set region={home} in the config."
        )
        return 2

    sizes = parse_sizes(args.sizes)
    live = [
        i
        for i in oci.pagination.list_call_get_all_results(compute.list_instances, compartment).data
        if i.lifecycle_state not in ("TERMINATED", "TERMINATING")
    ]
    mine = [i for i in live if i.display_name == args.name]
    if mine:
        log(f"an instance named {args.name!r} already exists ({mine[0].lifecycle_state}); stopping")
        return 0
    used_ocpus = sum(i.shape_config.ocpus for i in live if i.shape == SHAPE)
    used_mem = sum(i.shape_config.memory_in_gbs for i in live if i.shape == SHAPE)
    for ocpus, mem in sizes:
        if used_ocpus + ocpus > FREE_OCPUS or used_mem + mem > FREE_MEMORY_GB:
            log(
                f"{ocpus:g} OCPU / {mem:g} GB plus your existing A1 VMs "
                f"({used_ocpus:g} OCPU / {used_mem:g} GB) is over the free "
                f"{FREE_OCPUS} OCPU / {FREE_MEMORY_GB} GB; refusing"
            )
            return 2

    ads = [a.name for a in identity.list_availability_domains(compartment).data]
    images = [
        img
        for img in compute.list_images(
            compartment,
            operating_system="Canonical Ubuntu",
            operating_system_version="24.04",
            shape=SHAPE,
            sort_by="TIMECREATED",
            sort_order="DESC",
        ).data
        if "minimal" not in img.display_name.lower()
    ]
    if not images:
        log("no Ubuntu 24.04 image for A1 found")
        return 2
    image = images[0]
    subnet = public_subnet(vnet, compartment, create=not args.dry_run)
    key = ssh_public_key(Path(args.ssh_key).expanduser())

    log(f"home region {home}; availability domains: {', '.join(ads)}")
    log(
        f"image {image.display_name}; sizes {args.sizes}; subnet "
        f"{subnet.display_name if subnet else '(would be created)'}"
    )
    if args.dry_run:
        log("dry run: everything checks out, nothing launched")
        return 0
    for sl_id in subnet.security_list_ids:
        ensure_ports_open(vnet, sl_id)

    m = oci.core.models
    attempt, backoff = 0, 0
    while True:
        for ocpus, mem in sizes:
            for ad in ads:
                attempt += 1
                details = m.LaunchInstanceDetails(
                    availability_domain=ad,
                    compartment_id=compartment,
                    display_name=args.name,
                    shape=SHAPE,
                    shape_config=m.LaunchInstanceShapeConfigDetails(ocpus=ocpus, memory_in_gbs=mem),
                    source_details=m.InstanceSourceViaImageDetails(
                        image_id=image.id, boot_volume_size_in_gbs=50
                    ),
                    create_vnic_details=m.CreateVnicDetails(
                        subnet_id=subnet.id, assign_public_ip=True
                    ),
                    metadata={"ssh_authorized_keys": key},
                )
                try:
                    inst = compute.launch_instance(details).data
                except oci.exceptions.ServiceError as e:
                    text = (e.message or "").lower()
                    if e.status == 429:
                        backoff = min(backoff * 2 or 300, 1800)
                        log(f"attempt {attempt}: rate limited; waiting {backoff}s")
                        time.sleep(backoff)
                        continue
                    if any(h in text for h in CAPACITY_HINTS):
                        log(f"attempt {attempt}: no capacity for {ocpus:g}/{mem:g} in {ad}")
                        continue
                    log(f"attempt {attempt}: Oracle said {e.status} {e.code}: {e.message}")
                    return 1
                log(f"got it: {ocpus:g} OCPU / {mem:g} GB in {ad}; waiting for it to boot")
                oci.wait_until(
                    compute,
                    compute.get_instance(inst.id),
                    "lifecycle_state",
                    "RUNNING",
                    max_wait_seconds=900,
                )
                vnic_id = (
                    compute.list_vnic_attachments(compartment, instance_id=inst.id).data[0].vnic_id
                )
                ip = vnet.get_vnic(vnic_id).data.public_ip
                log(f"RUNNING. Public IP: {ip}")
                log(f"ssh -i {Path(args.ssh_key).expanduser().with_suffix('')} ubuntu@{ip}")
                print("\a", end="", flush=True)
                return 0
        backoff = 0
        wait = args.interval + random.randint(0, 60)
        log(f"no capacity this round; next try in {wait}s")
        time.sleep(wait)


if __name__ == "__main__":
    sys.exit(main())
