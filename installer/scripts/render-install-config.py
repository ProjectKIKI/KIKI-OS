#!/usr/bin/env python3
import argparse
import secrets
from pathlib import Path

try:
    import yaml
except ImportError as exc:
    raise SystemExit("python3-yaml or PyYAML is required") from exc


def main():
    parser = argparse.ArgumentParser(description="Render a node install.yaml from a template")
    parser.add_argument("--template", default="installer/configs/install.example.yaml")
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--role", choices=["controller", "compute"], required=True)
    parser.add_argument("--disk", default=None)
    parser.add_argument("--boot-mode", choices=["bios", "uefi"], default=None)
    parser.add_argument("--management-url", default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--registration-disabled", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.template, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    config["metadata"]["name"] = args.hostname
    spec = config["spec"]
    spec["hostname"] = args.hostname
    spec["role"] = args.role
    if args.disk:
        spec["storage"]["disk"] = args.disk
    if args.boot_mode:
        spec["storage"]["bootMode"] = args.boot_mode
    if args.management_url:
        spec["agent"]["managementUrl"] = args.management_url
    if args.registration_disabled:
        spec["agent"] = {"registrationRequired": False}
    else:
        spec["agent"]["registrationToken"] = args.token or secrets.token_urlsafe(32)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


if __name__ == "__main__":
    main()
