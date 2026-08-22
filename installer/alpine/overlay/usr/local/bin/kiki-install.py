#!/usr/bin/env python3
import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from urllib import error, request
from urllib.parse import urljoin
from urllib.parse import urlparse

try:
    import yaml
except ImportError as exc:
    raise SystemExit("py3-yaml or PyYAML is required to run kiki-install") from exc


DEFAULT_CONFIG = "/etc/kiki/install.yaml"
PINNED_TARGET_KERNEL_PACKAGE = "linux-image-6.1.0-51-amd64"
PINNED_TARGET_KERNEL_VERSION = "6.1.177-1"
DEFAULT_TARGET = "/mnt/kiki-target"


class InstallerError(RuntimeError):
    pass


class Runner:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run

    def run(self, args, check=True):
        printable = " ".join(str(arg) for arg in args)
        if self.dry_run:
            print(f"+ {printable}")
            return subprocess.CompletedProcess(args, 0)
        print(f"+ {printable}")
        return subprocess.run(args, check=check)

    def write_text(self, path, content, mode=0o644):
        path = Path(path)
        if self.dry_run:
            print(f"+ write {path}")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        os.chmod(path, mode)

    def mkdir(self, path):
        path = Path(path)
        if self.dry_run:
            print(f"+ mkdir -p {path}")
            return
        path.mkdir(parents=True, exist_ok=True)


def load_config(path):
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise InstallerError("install config must be a YAML mapping")
    return data


def require(mapping, dotted_path):
    cursor = mapping
    for part in dotted_path.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            raise InstallerError(f"missing required field: {dotted_path}")
        cursor = cursor[part]
    if cursor is None or cursor == "":
        raise InstallerError(f"empty required field: {dotted_path}")
    return cursor


def validate_config(config):
    if require(config, "apiVersion") != "kiki.io/v1alpha1":
        raise InstallerError("apiVersion must be kiki.io/v1alpha1")
    if require(config, "kind") != "KikiInstallConfig":
        raise InstallerError("kind must be KikiInstallConfig")

    required = [
        "metadata.name",
        "spec.hostname",
        "spec.role",
        "spec.clusterRef.name",
        "spec.os.distribution",
        "spec.os.release",
        "spec.os.mirror",
        "spec.os.securityMirror",
        "spec.os.architecture",
        "spec.os.kernelPackage",
        "spec.os.kernelVersion",
        "spec.storage.disk",
        "spec.storage.bootMode",
        "spec.storage.rootFs",
    ]
    for field in required:
        require(config, field)

    spec = config["spec"]
    if spec["os"]["distribution"] != "debian":
        raise InstallerError("only Debian target installs are supported")
    security_mirror = urlparse(spec["os"]["securityMirror"])
    if security_mirror.scheme != "https" or not security_mirror.netloc or security_mirror.username or security_mirror.password:
        raise InstallerError("spec.os.securityMirror must be credential-free HTTPS")
    if spec["os"]["kernelPackage"] != PINNED_TARGET_KERNEL_PACKAGE or spec["os"]["kernelVersion"] != PINNED_TARGET_KERNEL_VERSION:
        raise InstallerError(
            f"target kernel must be pinned to {PINNED_TARGET_KERNEL_PACKAGE}={PINNED_TARGET_KERNEL_VERSION}"
        )
    if spec["storage"]["bootMode"] not in ("bios", "uefi"):
        raise InstallerError("spec.storage.bootMode must be bios or uefi")
    if spec["storage"]["rootFs"] != "ext4":
        raise InstallerError("only ext4 root filesystem is supported")
    if spec["role"] not in ("controller", "compute"):
        raise InstallerError("spec.role must be controller or compute")
    registration_required = spec["agent"].get("registrationRequired", True)
    if not isinstance(registration_required, bool):
        raise InstallerError("spec.agent.registrationRequired must be a boolean")
    if registration_required:
        require(config, "spec.agent.managementUrl")
    if registration_required and not spec["agent"].get("registrationToken") and not spec["agent"].get("registrationTokenFile"):
        raise InstallerError("spec.agent.registrationToken or registrationTokenFile is required when registration is enabled")
    if registration_required and spec["agent"].get("registrationToken") == "CHANGE_ME" and not spec["agent"].get("allowInsecureToken", False):
        print("warning: spec.agent.registrationToken is CHANGE_ME; replace it before real installs")
    if spec.get("bootstrap", {}).get("installKubernetesTools"):
        require(config, "spec.bootstrap.kubernetesVersion")
    for index, mirror in enumerate(spec.get("images", {}).get("mirrors", [])):
        if not isinstance(mirror, dict):
            raise InstallerError(f"spec.images.mirrors[{index}] must be a mapping")
        if not mirror.get("registry") or not mirror.get("endpoint"):
            raise InstallerError(f"spec.images.mirrors[{index}] requires registry and endpoint")
    nvidia = spec.get("accelerators", {}).get("nvidia", {})
    if nvidia.get("enabled"):
        for field in (
            "repository",
            "keyURL",
            "keySHA256",
            "driverPackage",
            "driverVersion",
            "toolkitPackage",
            "toolkitVersion",
            "devicePluginImage",
        ):
            require(config, f"spec.accelerators.nvidia.{field}")
        for field in ("repository", "keyURL"):
            value = nvidia[field]
            parsed = urlparse(value)
            if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
                raise InstallerError(f"spec.accelerators.nvidia.{field} must be HTTPS without credentials")
        if not re.fullmatch(r"[a-f0-9]{64}", nvidia["keySHA256"]):
            raise InstallerError("spec.accelerators.nvidia.keySHA256 must be a lowercase SHA-256")
        for field in ("driverPackage", "toolkitPackage"):
            if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", nvidia[field]):
                raise InstallerError(f"spec.accelerators.nvidia.{field} is not a valid package name")
        for field in ("driverVersion", "toolkitVersion"):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+:~_-]*", nvidia[field]):
                raise InstallerError(f"spec.accelerators.nvidia.{field} is not a valid pinned version")
        if not re.fullmatch(r"[^\s@]+@sha256:[a-f0-9]{64}", nvidia["devicePluginImage"]):
            raise InstallerError("spec.accelerators.nvidia.devicePluginImage must be digest pinned")


def part_path(disk, number):
    if disk.startswith("/dev/nvme") or disk.startswith("/dev/mmcblk"):
        return f"{disk}p{number}"
    return f"{disk}{number}"


def partition_disk(runner, spec):
    storage = spec["storage"]
    disk = storage["disk"]
    boot_mode = storage["bootMode"]

    if storage.get("wipe") is not True:
        raise InstallerError("spec.storage.wipe must be true for this MVP installer")

    runner.run(["wipefs", "--all", "--force", disk])
    runner.run(["sgdisk", "--zap-all", disk])

    if boot_mode == "uefi":
        runner.run(["parted", "-s", disk, "mklabel", "gpt"])
        runner.run(["parted", "-s", disk, "mkpart", "ESP", "fat32", "1MiB", "513MiB"])
        runner.run(["parted", "-s", disk, "set", "1", "esp", "on"])
        runner.run(["parted", "-s", disk, "mkpart", "root", "ext4", "513MiB", "100%"])
        efi_part = part_path(disk, 1)
        root_part = part_path(disk, 2)
        runner.run(["mkfs.vfat", "-F32", efi_part])
    else:
        runner.run(["parted", "-s", disk, "mklabel", "gpt"])
        runner.run(["parted", "-s", disk, "mkpart", "bios_grub", "1MiB", "3MiB"])
        runner.run(["parted", "-s", disk, "set", "1", "bios_grub", "on"])
        runner.run(["parted", "-s", disk, "mkpart", "root", "ext4", "3MiB", "100%"])
        efi_part = None
        root_part = part_path(disk, 2)

    runner.run(["mkfs.ext4", "-F", root_part])
    return root_part, efi_part


def mount_target(runner, target, root_part, efi_part):
    runner.mkdir(target)
    runner.run(["mount", root_part, target])
    if efi_part:
        runner.mkdir(Path(target) / "boot/efi")
        runner.run(["mount", efi_part, str(Path(target) / "boot/efi")])


def debootstrap_target(runner, spec, target):
    os_spec = spec["os"]
    packages = list(os_spec.get("packages") or [])
    if "linux-image-amd64" in packages:
        packages.remove("linux-image-amd64")
    if os_spec["kernelPackage"] in packages:
        packages.remove(os_spec["kernelPackage"])
    for package in ("python3", "python3-yaml"):
        if package not in packages:
            packages.append(package)
    package_arg = ",".join(packages)
    command = [
        "debootstrap",
        f"--arch={os_spec['architecture']}",
    ]
    if package_arg:
        command.append(f"--include={package_arg}")
    command.extend([os_spec["release"], target, os_spec["mirror"]])
    runner.run(command)


def install_and_verify_target_kernel(runner, spec, target):
    os_spec = spec["os"]
    runner.write_text(
        Path(target) / "etc/apt/sources.list.d/kiki-security.list",
        f"deb {os_spec['securityMirror']} {os_spec['release']}-security main\n",
    )
    runner.run(["chroot", target, "apt-get", "update"])
    runner.run(
        [
            "chroot", target, "env", "DEBIAN_FRONTEND=noninteractive",
            "apt-get", "install", "-y", "--no-install-recommends",
            f"{os_spec['kernelPackage']}={os_spec['kernelVersion']}",
        ]
    )
    runner.run(["chroot", target, "apt-mark", "hold", os_spec["kernelPackage"]])
    runner.run(
        [
            "chroot",
            target,
            "/bin/sh",
            "-ec",
            'test "$(dpkg-query -W -f=\'${Version}\' "$1")" = "$2"',
            "kiki-kernel-version-check",
            os_spec["kernelPackage"],
            os_spec["kernelVersion"],
        ]
    )


def read_registration_token(agent, dry_run=False):
    if agent.get("registrationTokenFile"):
        if dry_run:
            return "DRY_RUN_TOKEN_FROM_FILE"
        return Path(agent["registrationTokenFile"]).read_text(encoding="utf-8").strip()
    return agent.get("registrationToken", "")


def target_token_source():
    return {"registrationTokenFile": "/etc/kiki/registration-token"}


def node_payload(config, phase, dry_run=False, node_token=None):
    spec = config["spec"]
    agent = spec["agent"]
    payload = {
        "apiVersion": "kiki.io/v1alpha1",
        "kind": "KikiNodeRegistration",
        "metadata": {"name": spec["hostname"]},
        "spec": {
            "phase": phase,
            "role": spec["role"],
            "clusterRef": {"name": spec["clusterRef"]["name"]},
            "os": {
                "distribution": spec["os"]["distribution"],
                "release": spec["os"]["release"],
                "architecture": spec["os"]["architecture"],
            },
            "storage": {
                "disk": spec["storage"]["disk"],
                "bootMode": spec["storage"]["bootMode"],
                "rootFs": spec["storage"]["rootFs"],
            },
            "bootstrap": spec.get("bootstrap", {}),
        },
    }
    if not node_token:
        payload["spec"]["registrationToken"] = read_registration_token(agent, dry_run=dry_run)
    return payload


def callback_url(agent):
    base = agent["managementUrl"].rstrip("/") + "/"
    path = agent.get("callbackPath", "/api/v1/nodes/register").lstrip("/")
    return urljoin(base, path)


def notify_management(config, phase, dry_run, node_token=None):
    agent = config["spec"]["agent"]
    if not agent.get("registrationRequired", True):
        return node_token
    payload = node_payload(config, phase, dry_run=dry_run, node_token=node_token)
    redacted = json.loads(json.dumps(payload))
    if "registrationToken" in redacted["spec"]:
        redacted["spec"]["registrationToken"] = "REDACTED"
    url = callback_url(agent)
    if dry_run:
        print(f"+ POST {url} {json.dumps(redacted, sort_keys=True)}")
        return node_token or "DRY_RUN_NODE_TOKEN"

    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "kiki-install/0.1"}
    if node_token:
        headers["Authorization"] = f"Bearer {node_token}"
    try:
        req = request.Request(url, data=body, headers=headers, method="POST")
        with request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result.get("nodeToken") or node_token
    except (error.URLError, TimeoutError) as exc:
        print(f"warning: management callback failed for phase {phase}: {exc}", file=sys.stderr)
        return node_token


def render_agent_script():
    return """#!/usr/bin/env python3
import json
import socket
import sys
import time
from pathlib import Path
from urllib import error, request
from urllib.parse import urljoin

try:
    import yaml
except ImportError:
    yaml = None

CONFIG_PATH = Path("/etc/kiki/node.yaml")


def load_config():
    data = CONFIG_PATH.read_text(encoding="utf-8")
    if yaml is not None:
        return yaml.safe_load(data)
    raise SystemExit("python3-yaml is required for kiki-agent")


def read_token(spec):
    if spec.get("registrationTokenFile"):
        return Path(spec["registrationTokenFile"]).read_text(encoding="utf-8").strip()
    return spec.get("registrationToken", "")


def post(url, payload, token=None):
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "kiki-agent/0.1"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    with request.urlopen(req, timeout=10) as response:
        data = response.read()
        return json.loads(data.decode("utf-8")) if data else {}


def persist_node_token(config, token):
    spec = config["spec"]
    token_path = Path(spec["registrationTokenFile"])
    token_tmp = token_path.with_suffix(token_path.suffix + ".tmp")
    token_tmp.write_text(token + "\n", encoding="utf-8")
    token_tmp.chmod(0o600)
    token_tmp.replace(token_path)
    spec["registrationPending"] = False
    config_tmp = CONFIG_PATH.with_suffix(".tmp")
    config_tmp.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    config_tmp.chmod(0o600)
    config_tmp.replace(CONFIG_PATH)


def main():
    config = load_config()
    spec = config["spec"]
    base = spec["managementUrl"].rstrip("/") + "/"
    callback_path = spec.get("callbackPath", "/api/v1/nodes/register").lstrip("/")
    heartbeat_path = spec.get("heartbeatPath", "/api/v1/nodes/heartbeat").lstrip("/")
    token = read_token(spec)
    payload = {
        "apiVersion": "kiki.io/v1alpha1",
        "kind": "KikiNodeRegistration",
        "metadata": {"name": config["metadata"]["name"]},
        "spec": {
            "phase": "booted",
            "hostname": socket.gethostname(),
            "role": spec["role"],
            "clusterRef": spec["clusterRef"],
            "kubernetes": spec.get("kubernetes", {}),
        },
    }
    if spec.get("registrationPending", False):
        payload["spec"]["registrationToken"] = token
        result = post(urljoin(base, callback_path), payload)
        token = result.get("nodeToken", "")
        if not token:
            raise RuntimeError("bootstrap registration did not return a node token")
        persist_node_token(config, token)
    else:
        post(urljoin(base, callback_path), payload, token=token)

    interval = int(spec.get("heartbeatIntervalSeconds", 0) or 0)
    if interval <= 0:
        return
    heartbeat = {
        "apiVersion": "kiki.io/v1alpha1",
        "kind": "KikiNodeHeartbeat",
        "metadata": {"name": config["metadata"]["name"]},
        "spec": {"role": spec["role"], "clusterRef": spec["clusterRef"]},
    }
    while True:
        try:
            post(urljoin(base, heartbeat_path), heartbeat, token=token)
        except (error.URLError, TimeoutError) as exc:
            print(f"heartbeat failed: {exc}", file=sys.stderr)
        time.sleep(interval)


if __name__ == "__main__":
    main()
"""


def render_kubernetes_bootstrap(spec):
    bootstrap = spec.get("bootstrap", {})
    version = str(bootstrap.get("kubernetesVersion", "1.30")).lstrip("v")
    join_command = bootstrap.get("joinCommand", "")
    return f"""#!/bin/sh
set -eu

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y apt-transport-https ca-certificates curl gpg
install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v{version}/deb/Release.key \
  | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v{version}/deb/ /' \
  > /etc/apt/sources.list.d/kubernetes.list
apt-get update
apt-get install -y kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl
systemctl enable kubelet

if [ -n "{join_command}" ]; then
  {join_command}
fi
"""


def configure_kubernetes_bootstrap(runner, spec, target):
    bootstrap = spec.get("bootstrap", {})
    if not bootstrap.get("installKubernetesTools", False):
        return
    runner.write_text(
        Path(target) / "usr/local/sbin/kiki-bootstrap-kubernetes",
        render_kubernetes_bootstrap(spec),
        mode=0o755,
    )
    runner.write_text(
        Path(target) / "etc/systemd/system/kiki-bootstrap-kubernetes.service",
        "\n".join(
            [
                "[Unit]",
                "Description=Install Kubernetes node tools for KIKI",
                "After=network-online.target",
                "Wants=network-online.target",
                "ConditionPathExists=!/var/lib/kiki/kubernetes-bootstrapped",
                "",
                "[Service]",
                "Type=oneshot",
                "ExecStart=/usr/local/sbin/kiki-bootstrap-kubernetes",
                "ExecStartPost=/bin/sh -c 'mkdir -p /var/lib/kiki && touch /var/lib/kiki/kubernetes-bootstrapped'",
                "RemainAfterExit=yes",
                "",
                "[Install]",
                "WantedBy=multi-user.target",
                "",
            ]
        ),
    )


def render_hosts_toml(registry, mirror):
    endpoint = mirror["endpoint"].rstrip("/")
    server_scheme = "http" if mirror.get("plainHttp", False) else "https"
    lines = [
        f'server = "{server_scheme}://{registry}"',
        "",
        f'[host."{endpoint}"]',
        '  capabilities = ["pull", "resolve"]',
    ]
    if mirror.get("skipVerify", False):
        lines.append("  skip_verify = true")
    return "\n".join(lines) + "\n"


def configure_image_mirrors(runner, spec, target):
    images = spec.get("images", {})
    mirrors = images.get("mirrors") or []
    pre_pull = images.get("prePull") or []
    if not mirrors and not pre_pull:
        return

    runner.mkdir(Path(target) / "etc/containerd")
    runner.write_text(
        Path(target) / "etc/containerd/config.toml",
        "\n".join(
            [
                "version = 2",
                "",
                '[plugins."io.containerd.grpc.v1.cri".registry]',
                '  config_path = "/etc/containerd/certs.d"',
                "",
            ]
        ),
    )

    for mirror in mirrors:
        registry = mirror["registry"].strip("/")
        runner.write_text(
            Path(target) / "etc/containerd/certs.d" / registry / "hosts.toml",
            render_hosts_toml(registry, mirror),
        )

    if pre_pull:
        commands = ["#!/bin/sh", "set -eu", ""]
        commands.extend(f"ctr -n k8s.io images pull {image}" for image in pre_pull)
        runner.write_text(
            Path(target) / "usr/local/sbin/kiki-prepull-images",
            "\n".join(commands) + "\n",
            mode=0o755,
        )
        runner.write_text(
            Path(target) / "etc/systemd/system/kiki-prepull-images.service",
            "\n".join(
                [
                    "[Unit]",
                    "Description=Pre-pull KIKI bootstrap container images",
                    "After=containerd.service network-online.target",
                    "Wants=network-online.target",
                    "Requires=containerd.service",
                    "ConditionPathExists=!/var/lib/kiki/images-prepulled",
                    "",
                    "[Service]",
                    "Type=oneshot",
                    "ExecStart=/usr/local/sbin/kiki-prepull-images",
                    "ExecStartPost=/bin/sh -c 'mkdir -p /var/lib/kiki && touch /var/lib/kiki/images-prepulled'",
                    "RemainAfterExit=yes",
                    "",
                    "[Install]",
                    "WantedBy=multi-user.target",
                    "",
                ]
            ),
        )


def render_nvidia_setup(nvidia):
    repository = shlex.quote(nvidia["repository"].rstrip("/"))
    key_url = shlex.quote(nvidia["keyURL"])
    key_sha256 = shlex.quote(nvidia["keySHA256"])
    driver = shlex.quote(f'{nvidia["driverPackage"]}={nvidia["driverVersion"]}')
    toolkit = shlex.quote(f'{nvidia["toolkitPackage"]}={nvidia["toolkitVersion"]}')
    return "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            "key_file=$(mktemp)",
            "trap 'rm -f \"$key_file\"' EXIT",
            f"curl --fail --location --proto '=https' --tlsv1.2 {key_url} --output \"$key_file\"",
            f"echo {key_sha256}'  '\"$key_file\" | sha256sum -c -",
            "install -d -m 0755 /etc/apt/keyrings",
            "gpg --batch --yes --dearmor --output /etc/apt/keyrings/kiki-nvidia.gpg \"$key_file\"",
            f"echo 'deb [signed-by=/etc/apt/keyrings/kiki-nvidia.gpg] '" + repository + "' /' > /etc/apt/sources.list.d/kiki-nvidia.list",
            "apt-get update",
            f"DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends {driver} {toolkit}",
            "nvidia-ctk runtime configure --runtime=containerd",
            "systemctl restart containerd",
            "nvidia-smi",
            "install -d -m 0755 /var/lib/kiki",
            "touch /var/lib/kiki/nvidia-runtime-configured",
            "",
        ]
    )


def render_nvidia_device_plugin(nvidia):
    image = nvidia["devicePluginImage"]
    return yaml.safe_dump(
        {
            "apiVersion": "apps/v1",
            "kind": "DaemonSet",
            "metadata": {"name": "kiki-nvidia-device-plugin", "namespace": "kube-system"},
            "spec": {
                "selector": {"matchLabels": {"app.kubernetes.io/name": "kiki-nvidia-device-plugin"}},
                "template": {
                    "metadata": {"labels": {"app.kubernetes.io/name": "kiki-nvidia-device-plugin"}},
                    "spec": {
                        "automountServiceAccountToken": False,
                        "priorityClassName": "system-node-critical",
                        "nodeSelector": {"kiki.io/accelerator": "nvidia"},
                        "tolerations": [{"operator": "Exists"}],
                        "containers": [
                            {
                                "name": "device-plugin",
                                "image": image,
                                "imagePullPolicy": "IfNotPresent",
                                "securityContext": {
                                    "allowPrivilegeEscalation": False,
                                    "readOnlyRootFilesystem": True,
                                    "capabilities": {"drop": ["ALL"]},
                                },
                                "volumeMounts": [
                                    {
                                        "name": "device-plugin",
                                        "mountPath": "/var/lib/kubelet/device-plugins",
                                    }
                                ],
                            }
                        ],
                        "volumes": [
                            {
                                "name": "device-plugin",
                                "hostPath": {
                                    "path": "/var/lib/kubelet/device-plugins",
                                    "type": "Directory",
                                },
                            }
                        ],
                    },
                },
            },
        },
        sort_keys=False,
    )


def configure_accelerators(runner, spec, target):
    nvidia = spec.get("accelerators", {}).get("nvidia", {})
    if not nvidia.get("enabled"):
        return
    runner.write_text(
        Path(target) / "usr/local/sbin/kiki-configure-nvidia",
        render_nvidia_setup(nvidia),
        mode=0o755,
    )
    runner.write_text(
        Path(target) / "etc/systemd/system/kiki-configure-nvidia.service",
        "\n".join(
            [
                "[Unit]",
                "Description=Configure NVIDIA runtime for KIKI containerd nodes",
                "After=network-online.target containerd.service",
                "Wants=network-online.target",
                "Requires=containerd.service",
                "Before=kubelet.service",
                "ConditionPathExists=!/var/lib/kiki/nvidia-runtime-configured",
                "",
                "[Service]",
                "Type=oneshot",
                "ExecStart=/usr/local/sbin/kiki-configure-nvidia",
                "RemainAfterExit=yes",
                "",
                "[Install]",
                "WantedBy=multi-user.target",
                "",
            ]
        ),
    )
    runner.write_text(
        Path(target) / "etc/kiki/manifests/nvidia-device-plugin.yaml",
        render_nvidia_device_plugin(nvidia),
        mode=0o600,
    )
    runner.write_text(
        Path(target) / "etc/default/kubelet",
        'KUBELET_EXTRA_ARGS="--node-labels=kiki.io/accelerator=nvidia,kiki.io/runtime-vllm=true"\n',
    )

def configure_target(runner, config, target, node_token=None):
    spec = config["spec"]
    hostname = spec["hostname"]
    role = spec["role"]
    cluster_name = spec["clusterRef"]["name"]
    agent = spec["agent"]
    registration_required = agent.get("registrationRequired", True)
    bootstrap = spec.get("bootstrap", {})

    runner.write_text(Path(target) / "etc/hostname", f"{hostname}\n")
    runner.write_text(
        Path(target) / "etc/hosts",
        "\n".join(
            [
                "127.0.0.1 localhost",
                f"127.0.1.1 {hostname}",
                "",
                "# The following lines are desirable for IPv6 capable hosts",
                "::1 localhost ip6-localhost ip6-loopback",
                "ff02::1 ip6-allnodes",
                "ff02::2 ip6-allrouters",
                "",
            ]
        ),
    )

    if spec.get("network", {}).get("dhcp", True):
        runner.mkdir(Path(target) / "etc/systemd/network")
        runner.write_text(
            Path(target) / "etc/systemd/network/20-kiki-dhcp.network",
            "[Match]\nName=en*\nName=eth*\n\n[Network]\nDHCP=yes\n",
        )

    runner.mkdir(Path(target) / "etc/kiki")
    if registration_required:
        runner.write_text(
            Path(target) / "etc/kiki/registration-token",
            (node_token or read_registration_token(agent, dry_run=runner.dry_run)) + "\n",
            mode=0o600,
        )
    else:
        runner.write_text(
            Path(target) / "etc/kiki/provisioning-required",
            "Inject node identity and registration credentials, then enable kiki-agent.service.\n",
            mode=0o600,
        )
    runner.write_text(
        Path(target) / "etc/kiki/node.yaml",
        yaml.safe_dump(
            {
                "apiVersion": "kiki.io/v1alpha1",
                "kind": "KikiNode",
                "metadata": {"name": hostname},
                "spec": {
                    "role": role,
                    "clusterRef": {"name": cluster_name},
                    "managementUrl": agent.get("managementUrl", ""),
                    "callbackPath": agent.get("callbackPath", "/api/v1/nodes/register"),
                    "heartbeatPath": agent.get("heartbeatPath", "/api/v1/nodes/heartbeat"),
                    "heartbeatIntervalSeconds": agent.get("heartbeatIntervalSeconds", 60),
                    "registrationPending": registration_required and not bool(node_token),
                    "kubernetes": {
                        "installTools": bootstrap.get("installKubernetesTools", False),
                        "version": bootstrap.get("kubernetesVersion", ""),
                    },
                    "images": spec.get("images", {}),
                    "accelerators": spec.get("accelerators", {}),
                    **(target_token_source() if registration_required else {"registrationRequired": False}),
                },
            },
            sort_keys=False,
        ),
        mode=0o600,
    )

    runner.write_text(
        Path(target) / "usr/local/bin/kiki-agent",
        render_agent_script(),
        mode=0o755,
    )
    runner.write_text(
        Path(target) / "etc/systemd/system/kiki-agent.service",
        "\n".join(
            [
                "[Unit]",
                "Description=KIKI node registration agent",
                "After=network-online.target",
                "Wants=network-online.target",
                "",
                "[Service]",
                "Type=simple",
                "Restart=on-failure",
                "RestartSec=30s",
                "ExecStart=/usr/local/bin/kiki-agent",
                "",
                "[Install]",
                "WantedBy=multi-user.target",
                "",
            ]
        ),
    )
    configure_kubernetes_bootstrap(runner, spec, target)
    configure_image_mirrors(runner, spec, target)
    configure_accelerators(runner, spec, target)
    runner.write_text(
        Path(target) / "etc/default/grub.d/kiki-serial.cfg",
        '\n'.join(
            [
                'GRUB_CMDLINE_LINUX_DEFAULT="console=tty0 console=ttyS0,115200n8"',
                'GRUB_TERMINAL="console serial"',
                'GRUB_SERIAL_COMMAND="serial --speed=115200 --unit=0 --word=8 --parity=no --stop=1"',
                '',
            ]
        ),
    )


def install_bootloader(runner, spec, target):
    disk = spec["storage"]["disk"]
    boot_mode = spec["storage"]["bootMode"]

    runner.run(["mount", "--bind", "/dev", str(Path(target) / "dev")])
    runner.run(["mount", "--bind", "/proc", str(Path(target) / "proc")])
    runner.run(["mount", "--bind", "/sys", str(Path(target) / "sys")])

    runner.run(["chroot", target, "systemctl", "enable", "systemd-networkd"])
    runner.run(["chroot", target, "systemctl", "enable", "systemd-resolved"])
    runner.run(["chroot", target, "systemctl", "enable", "ssh"])
    if spec.get("agent", {}).get("registrationRequired", True):
        runner.run(["chroot", target, "systemctl", "enable", "kiki-agent.service"])
    if spec.get("images", {}).get("mirrors") or spec.get("images", {}).get("prePull"):
        runner.run(["chroot", target, "systemctl", "enable", "containerd"])
    if spec.get("images", {}).get("prePull"):
        runner.run(["chroot", target, "systemctl", "enable", "kiki-prepull-images.service"])
    if spec.get("bootstrap", {}).get("installKubernetesTools", False):
        runner.run(["chroot", target, "systemctl", "enable", "kiki-bootstrap-kubernetes.service"])
    if spec.get("accelerators", {}).get("nvidia", {}).get("enabled", False):
        runner.run(["chroot", target, "systemctl", "enable", "containerd"])
        runner.run(["chroot", target, "systemctl", "enable", "kiki-configure-nvidia.service"])

    if boot_mode == "uefi":
        runner.run(
            [
                "chroot",
                target,
                "grub-install",
                "--target=x86_64-efi",
                "--efi-directory=/boot/efi",
                "--bootloader-id=KIKI",
            ]
        )
    else:
        runner.run(["chroot", target, "grub-install", "--target=i386-pc", disk])
    runner.run(["chroot", target, "update-grub"])


def cleanup(runner, target):
    mount_points = [
        Path(target) / "dev",
        Path(target) / "proc",
        Path(target) / "sys",
        Path(target) / "boot/efi",
        Path(target),
    ]
    for mount_point in mount_points:
        if runner.dry_run:
            print(f"+ umount -lf {mount_point}")
            continue
        subprocess.run(["umount", "-lf", str(mount_point)], check=False)


def assert_runtime_tools(dry_run):
    tools = [
        "wipefs",
        "sgdisk",
        "parted",
        "mkfs.ext4",
        "debootstrap",
        "mount",
        "chroot",
        "grub-install",
    ]
    missing = [tool for tool in tools if shutil.which(tool) is None]
    if missing and not dry_run:
        raise InstallerError(f"missing runtime tools: {', '.join(missing)}")
    if missing and dry_run:
        print(f"warning: missing runtime tools in dry-run environment: {', '.join(missing)}")


def install(config, target, dry_run):
    runner = Runner(dry_run=dry_run)
    spec = config["spec"]
    assert_runtime_tools(dry_run)
    node_token = notify_management(config, "installing", dry_run)
    root_part, efi_part = partition_disk(runner, spec)
    try:
        mount_target(runner, target, root_part, efi_part)
        debootstrap_target(runner, spec, target)
        install_and_verify_target_kernel(runner, spec, target)
        configure_target(runner, config, target, node_token=node_token)
        install_bootloader(runner, spec, target)
        notify_management(config, "installed", dry_run, node_token=node_token)
    finally:
        cleanup(runner, target)


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Install a Debian KIKI node from Alpine")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help=f"config path (default: {DEFAULT_CONFIG})")
    parser.add_argument("--target", default=DEFAULT_TARGET, help=f"target mount path (default: {DEFAULT_TARGET})")
    parser.add_argument("--dry-run", action="store_true", help="print actions without changing disks")
    parser.add_argument("--yes", action="store_true", help="allow destructive disk installation")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    config = load_config(args.config)
    validate_config(config)

    if not args.dry_run and not args.yes:
        raise InstallerError("real installation is destructive; pass --yes to continue")

    install(config, args.target, args.dry_run)
    if args.dry_run:
        print("dry-run completed")
    else:
        print("installation completed; reboot into the target disk")


if __name__ == "__main__":
    try:
        main()
    except InstallerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
