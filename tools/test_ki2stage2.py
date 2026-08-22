from __future__ import annotations

import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

import ki2stage2


def yaml_list(values: set[str], indent: int = 4) -> str:
    spaces = " " * indent
    return "\n".join(f"{spaces}- {value}" for value in sorted(values))


def yaml_services(values: set[str]) -> str:
    return "\n".join(f"      - {value}" for value in sorted(values))


def write_profile(root: Path, name: str, runtime: str, *, extra_packages: set[str] | None = None) -> None:
    required, _forbidden, required_service, _forbidden_service = ki2stage2.expected_runtime_packages(runtime)
    kubeadm = ki2stage2.expected_kubeadm_contract(name, runtime)
    packages = set(required)
    packages.update(extra_packages or set())
    services = {"kubelet.service", "chronyd.service", required_service}
    profile = root / "distro" / "profiles" / f"{name}.yaml"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(
        "profile:\n"
        f"  name: {name}\n"
        "  description: test profile\n"
        "  packages:\n"
        f"{yaml_list(packages)}\n"
        "  services:\n"
        "    enable:\n"
        f"{yaml_services(services)}\n",
        encoding="utf-8",
    )

    plan = root / "distro" / "install-plans" / f"{name}.yaml"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        "install_plan:\n"
        f"  name: {name}\n"
        "  package_sets:\n"
        "    kubernetes:\n"
        f"{yaml_list(packages, indent=6)}\n"
        "  post_install:\n"
        "    enable_services:\n"
        f"{yaml_services(services)}\n"
        "  runtime:\n"
        f"    container_runtime: {runtime}\n"
        "  kubernetes:\n"
        f"    role: {kubeadm['role']}\n"
        "    kubeadm:\n"
        f"      config_api: {ki2stage2.KUBEADM_CONFIG_API}\n"
        f"      action: {kubeadm['action']}\n"
        f"      config_template: {kubeadm['template']}\n"
        f"      config_output: {ki2stage2.KUBEADM_LOCAL_CONFIG}\n"
        f"      command: {kubeadm['command']}\n"
        f"      control_plane: {str(kubeadm['control_plane']).lower()}\n"
        f"      cri_socket: {kubeadm['cri_socket']}\n",
        encoding="utf-8",
    )


def write_containerd_recipe(root: Path) -> None:
    recipe_dir = root / "distro" / "recipes"
    recipe_dir.mkdir(parents=True, exist_ok=True)
    (recipe_dir / "kubernetes.yaml").write_text(
        "recipes:\n"
        "  - name: containerd\n"
        "    version: \"2.1.0\"\n"
        "    release: 2\n"
        "    summary: containerd\n"
        "    license: Apache-2.0\n"
        "    tier: kubernetes\n"
        "    architectures: [x86_64]\n"
        "    source:\n"
        "      type: virtual\n"
        "    depends:\n"
        "      build: []\n"
        "      runtime: [glibc, runc, systemd]\n"
        "    build:\n"
        "      system: stage2-stub\n",
        encoding="utf-8",
    )


def write_network_userspace_repo(root: Path, *, placeholder: bool = True) -> None:
    recipe_dir = root / "distro" / "recipes"
    recipe_dir.mkdir(parents=True, exist_ok=True)
    lines = ["recipes:\n"]
    for name in ki2stage2.NETWORK_USERSPACE_PACKAGES:
        lines.extend(
            [
                f"  - name: {name}\n",
                "    version: \"2.1.0\"\n",
                "    release: 2\n",
                f"    summary: {name}\n",
                "    license: GPL-2.0-only\n",
                "    tier: network\n",
                "    architectures: [x86_64]\n",
                "    source:\n",
                "      type: virtual\n",
                "    depends:\n",
                "      build: []\n",
                "      runtime: [glibc]\n",
                "    build:\n",
                f"      system: {'stage2-stub' if placeholder else 'upstream-binary'}\n",
            ]
        )
    (recipe_dir / "network.yaml").write_text("".join(lines), encoding="utf-8")

    for name, requirement in ki2stage2.NETWORK_USERSPACE_REQUIREMENTS.items():
        files = {path: f"{name} payload\n" for path in requirement.paths}
        for path, needles in requirement.contains.items():
            files[path] = "\n".join(needles) + "\n"
        if placeholder:
            files[f"/usr/share/kiki/stage2/{name}.json"] = json.dumps({"schema": "kiki-stage2-placeholder-v1"})
        write_ki2_package(root, name, files)


def write_ki2_package(root: Path, name: str, files: dict[str, str]) -> None:
    package_dir = root / "dist" / "ki2" / "packages" / "x86_64"
    package_dir.mkdir(parents=True, exist_ok=True)
    package = package_dir / f"{name}-2.1.0-2.x86_64.ki2"
    manifest = {
        "schema": "ki2-package-v1",
        "name": name,
        "version": "2.1.0",
        "release": "2",
        "arch": "x86_64",
        "summary": name,
        "license": "Apache-2.0",
        "tier": "kubernetes",
        "dependencies": {"build": [], "runtime": ["glibc", "runc", "systemd"]},
        "runtime_dependencies": ["glibc", "runc", "systemd"],
        "payload": {"rootfs_prefix": "rootfs/", "contains_os_tree": True, "file_count": len(files)},
        "files": [{"path": path, "type": "file", "mode": "0o644"} for path in files],
    }
    with tarfile.open(package, "w:gz") as tar:
        body = json.dumps(manifest).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(body)
        tar.addfile(info, io.BytesIO(body))
        for path, text in files.items():
            payload = text.encode("utf-8")
            info = tarfile.TarInfo("rootfs/" + path.strip("/"))
            info.size = len(payload)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(payload))


def append_rootfs_file(root: Path, path: str, text: str) -> None:
    target = root / path.strip("/")
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    target.write_text(existing + text, encoding="utf-8")


def write_kubernetes_rootfs(root: Path, runtime: str, *, extra_installed: set[str] | None = None) -> None:
    required, _forbidden, required_service, _forbidden_service = ki2stage2.expected_runtime_packages(runtime)
    packages = sorted(required | (extra_installed or set()))
    state = root / "var/lib/ki2"
    state.mkdir(parents=True, exist_ok=True)
    (state / "installed.list").write_text("\n".join(packages) + "\n", encoding="utf-8")

    for name in sorted(required & set(ki2stage2.PAYLOAD_REQUIREMENTS)):
        requirement = ki2stage2.PAYLOAD_REQUIREMENTS[name]
        for path in requirement.paths:
            append_rootfs_file(root, path, f"{name} placeholder\n")
        for path, needles in requirement.contains.items():
            append_rootfs_file(root, path, "\n".join(needles) + "\n")

    wants = root / "etc/systemd/system/multi-user.target.wants"
    wants.mkdir(parents=True, exist_ok=True)
    (wants / required_service).write_text("enabled\n", encoding="utf-8")
    (wants / "kubelet.service").write_text("enabled\n", encoding="utf-8")
    (root / "etc/fstab").parent.mkdir(parents=True, exist_ok=True)
    (root / "etc/fstab").write_text("# swap intentionally disabled for Kubernetes\n", encoding="utf-8")


def write_stage2_install_plan(path: Path, runtime: str, role: str) -> None:
    required, _forbidden, required_service, _forbidden_service = ki2stage2.expected_runtime_packages(runtime)
    kubeadm = ki2stage2.expected_kubeadm_contract_for_role(role, runtime)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "install_plan:\n"
        "  schema: kiki-install-plan-v1\n"
        "  api_version: kiki.io/v1alpha1\n"
        "  kind: InstallPlan\n"
        "  source:\n"
        "    repo_index: /run/install-media/kiki/repo/index.x86_64.json\n"
        "    channel: stage2-v2\n"
        "  target:\n"
        "    filesystems:\n"
        "      swap:\n"
        "        enabled: false\n"
        "        policy: kubernetes-off\n"
        "  packages:\n"
        "    dependency_resolution: true\n"
        "    selected:\n"
        f"{yaml_list(required, indent=6)}\n"
        "  services:\n"
        "    enable:\n"
        f"{yaml_services({'kubelet.service', required_service})}\n"
        "  runtime:\n"
        f"    container_runtime: {runtime}\n"
        "    cgroup_driver: systemd\n"
        "    swap_policy: kubernetes-off\n"
        "  kubernetes:\n"
        f"    role: {role}\n"
        "    kubeadm:\n"
        f"      config_api: {ki2stage2.KUBEADM_CONFIG_API}\n"
        f"      action: {kubeadm['action']}\n"
        f"      config_template: {kubeadm['template']}\n"
        f"      config_output: {ki2stage2.KUBEADM_LOCAL_CONFIG}\n"
        f"      command: {kubeadm['command']}\n"
        f"      control_plane: {str(kubeadm['control_plane']).lower()}\n"
        f"      cri_socket: {kubeadm['cri_socket']}\n"
        "  artifacts:\n"
        "    runtime_plan: /run/kiki/install-plan.yaml\n"
        "    installed_plan: /var/lib/ki2/install-plan.yaml\n",
        encoding="utf-8",
    )


def write_install_plan_spec(root: Path, *, include_artifacts: bool = True) -> None:
    specs = root / "distro" / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    required = [
        "schema",
        "api_version",
        "kind",
        "mode",
        "source",
        "target",
        "identity",
        "network",
        "users",
        "packages",
        "services",
        "boot",
        "runtime",
        "kubernetes",
        "firewall",
    ]
    if include_artifacts:
        required.append("artifacts")
    (specs / "kiki-install-plan-v1.yaml").write_text(
        "schema: kiki-install-plan-spec-v1\n"
        "name: kiki-install-plan-v1\n"
        "status: stage2-v2\n"
        "document:\n"
        "  generated_runtime_path: /run/kiki/install-plan.yaml\n"
        "  installed_copy_path: /var/lib/ki2/install-plan.yaml\n"
        "required:\n"
        f"{yaml_list(set(required), indent=2)}\n"
        "optional: []\n"
        "kubernetes:\n"
        "  role: role\n"
        "  kubeadm:\n"
        "    config_api: api\n"
        "    action: action\n"
        "    config_template: template\n"
        "    config_output: output\n"
        "    command: command\n"
        "    control_plane: flag\n"
        "    cri_socket: socket\n"
        "artifacts:\n"
        "  runtime_plan: /run/kiki/install-plan.yaml\n"
        "  installed_plan: /var/lib/ki2/install-plan.yaml\n"
        "safety:\n"
        "  rules:\n"
        "    - containerd uses unix:///run/containerd/containerd.sock\n"
        "    - crio uses unix:///var/run/crio/crio.sock\n"
        "    - kiki.autoinstall requires explicit erase or quick-vm\n"
        "    - kiki.target must be a whole disk\n",
        encoding="utf-8",
    )


class Ki2Stage2Tests(unittest.TestCase):
    def test_install_plan_spec_accepts_stage2_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_install_plan_spec(root)

            verifier = ki2stage2.Verifier()
            ki2stage2.verify_install_plan_spec(root, verifier)

            self.assertEqual(verifier.errors, [])

    def test_install_plan_spec_rejects_missing_stage2_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_install_plan_spec(root, include_artifacts=False)

            verifier = ki2stage2.Verifier()
            ki2stage2.verify_install_plan_spec(root, verifier)

            self.assertTrue(any("requires Stage 2 sections" in item for item in verifier.errors))

    def test_profile_contracts_accept_crio_and_containerd_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, runtime in ki2stage2.PROFILE_SPECS:
                write_profile(root, name, runtime)

            verifier = ki2stage2.Verifier()
            ki2stage2.verify_profile_contracts(root, verifier)

            self.assertEqual(verifier.errors, [])

    def test_profile_contracts_reject_mixed_cri_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, runtime in ki2stage2.PROFILE_SPECS:
                extra = {"cri-o"} if name == "kiki-kube-compute-containerd" else set()
                write_profile(root, name, runtime, extra_packages=extra)

            verifier = ki2stage2.Verifier()
            ki2stage2.verify_profile_contracts(root, verifier)

            self.assertTrue(any("kiki-kube-compute-containerd: profile excludes opposite CRI package set" in item for item in verifier.errors))

    def test_package_payload_check_validates_required_paths_and_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_containerd_recipe(root)
            requirement = ki2stage2.PAYLOAD_REQUIREMENTS["containerd"]
            files = {path: "placeholder\n" for path in requirement.paths}
            files["/etc/containerd/config.toml"] = "version = 2\nruntime_type = \"io.containerd.runc.v2\"\nSystemdCgroup = true\n"
            files["/usr/lib/systemd/system/containerd.service"] = "ExecStart=/usr/bin/containerd\n"
            write_ki2_package(root, "containerd", files)

            verifier = ki2stage2.Verifier()
            ki2stage2.verify_package_payloads(root, "x86_64", verifier, package_names=["containerd"])

            self.assertEqual(verifier.errors, [])
            self.assertTrue(any("stage2-stub" in item for item in verifier.warnings))

    def test_network_userspace_verifier_reports_placeholder_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_network_userspace_repo(root, placeholder=True)

            verifier = ki2stage2.Verifier()
            ki2stage2.verify_network_userspace(root, "x86_64", verifier)

            self.assertEqual(verifier.errors, [])
            self.assertTrue(any("network userspace still uses stage2-stub" in item for item in verifier.warnings))

    def test_network_userspace_strict_mode_rejects_placeholder_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_network_userspace_repo(root, placeholder=True)

            verifier = ki2stage2.Verifier()
            ki2stage2.verify_network_userspace(root, "x86_64", verifier, strict_production=True)

            self.assertTrue(any("network userspace still uses stage2-stub" in item for item in verifier.errors))

    def test_network_userspace_rejects_embedded_host_glibc_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_network_userspace_repo(root, placeholder=False)
            requirement = ki2stage2.NETWORK_USERSPACE_REQUIREMENTS["nftables"]
            files = {path: "nftables payload\n" for path in requirement.paths}
            for path, needles in requirement.contains.items():
                files[path] = "\n".join(needles) + "\n"
            files["/lib64/libc.so.6"] = "host glibc placeholder\n"
            write_ki2_package(root, "nftables", files)

            verifier = ki2stage2.Verifier()
            ki2stage2.verify_network_userspace(root, "x86_64", verifier, strict_production=True)

            self.assertTrue(any("does not embed host glibc/core runtime" in item for item in verifier.errors))

    def test_repository_metadata_can_require_stage2_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "dist" / "ki2" / "repo"
            repo.mkdir(parents=True)
            (repo / "index.x86_64.json").write_text("{}\n", encoding="utf-8")
            metadata = {
                "channel": "stage2-v2",
                "index": {"package_count": len(ki2stage2.PAYLOAD_REQUIREMENTS)},
                "security": {
                    "signed": True,
                    "algorithm": "hmac-sha256",
                    "signature": "test-signature",
                },
            }
            (repo / "metadata.x86_64.json").write_text(json.dumps(metadata), encoding="utf-8")

            verifier = ki2stage2.Verifier()
            ki2stage2.verify_repository_metadata(root, "x86_64", verifier, require_signed=True)

            self.assertEqual(verifier.errors, [])

    def test_repository_metadata_rejects_unsigned_stage2_when_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "dist" / "ki2" / "repo"
            repo.mkdir(parents=True)
            (repo / "index.x86_64.json").write_text("{}\n", encoding="utf-8")
            metadata = {
                "channel": "stage2-v2",
                "index": {"package_count": len(ki2stage2.PAYLOAD_REQUIREMENTS)},
                "security": {"signed": False, "signature": None},
            }
            (repo / "metadata.x86_64.json").write_text(json.dumps(metadata), encoding="utf-8")

            verifier = ki2stage2.Verifier()
            ki2stage2.verify_repository_metadata(root, "x86_64", verifier, require_signed=True)

            self.assertTrue(any("repository metadata is signed" in item for item in verifier.errors))

    def test_installed_rootfs_accepts_containerd_kubernetes_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_kubernetes_rootfs(root, "containerd")

            verifier = ki2stage2.Verifier()
            ki2stage2.verify_installed_rootfs(root, "containerd", verifier)

            self.assertEqual(verifier.errors, [])

    def test_installed_rootfs_rejects_mixed_cri_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_kubernetes_rootfs(root, "containerd", extra_installed={"cri-o"})

            verifier = ki2stage2.Verifier()
            ki2stage2.verify_installed_rootfs(root, "containerd", verifier)

            self.assertTrue(any("excludes opposite CRI package set" in item for item in verifier.errors))

    def test_binary_smoke_commands_cover_runtime_and_kubernetes_binaries(self):
        paths = {command.path for command in ki2stage2.BINARY_SMOKE_COMMANDS}
        packages = {command.package for command in ki2stage2.BINARY_SMOKE_COMMANDS}

        self.assertTrue({"/usr/bin/crio", "/usr/bin/containerd", "/usr/bin/kubelet", "/usr/bin/kubeadm", "/usr/bin/kubectl"} <= paths)
        self.assertTrue({"cri-o", "containerd", "cri-tools", "kubelet", "kubeadm", "kubectl"} <= packages)

    def test_kubeadm_contracts_distinguish_node_roles_and_runtime_sockets(self):
        bootstrap = ki2stage2.expected_kubeadm_contract("kiki-kube-bootstrap", "cri-o")
        control = ki2stage2.expected_kubeadm_contract("kiki-kube-control-containerd", "containerd")
        compute = ki2stage2.expected_kubeadm_contract("kiki-kube-compute", "cri-o")

        self.assertEqual(bootstrap["action"], "init")
        self.assertEqual(bootstrap["template"], "/etc/kubernetes/kiki/kubeadm-init.yaml")
        self.assertTrue(bootstrap["control_plane"])
        self.assertEqual(control["template"], "/etc/kubernetes/kiki/kubeadm-join-control-plane.yaml")
        self.assertEqual(control["cri_socket"], "unix:///run/containerd/containerd.sock")
        self.assertEqual(compute["template"], "/etc/kubernetes/kiki/kubeadm-join-compute.yaml")
        self.assertFalse(compute["control_plane"])

    def test_kubeadm_config_smoke_covers_all_role_templates(self):
        self.assertEqual(
            set(ki2stage2.KUBEADM_TEMPLATES),
            {
                "/etc/kubernetes/kiki/kubeadm-init.yaml",
                "/etc/kubernetes/kiki/kubeadm-join-control-plane.yaml",
                "/etc/kubernetes/kiki/kubeadm-join-compute.yaml",
            },
        )
        self.assertEqual(set(ki2stage2.KUBEADM_CONFIG_PACKAGES), {"kube-node-config", "kube-node-config-containerd"})

    def test_package_manager_verifier_exposes_cli_command(self):
        parser = ki2stage2.build_parser()
        args = parser.parse_args(["verify-package-manager", "--repo-root", "/repo"])
        self.assertEqual(args.func, ki2stage2.command_verify_package_manager)

    def test_network_userspace_verifier_exposes_cli_command(self):
        parser = ki2stage2.build_parser()
        args = parser.parse_args(["verify-network-userspace", "--repo-root", "/repo", "--strict-production"])
        self.assertEqual(args.func, ki2stage2.command_verify_network_userspace)
        self.assertTrue(args.strict_production)

    def test_stage2_install_plan_accepts_containerd_compute_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "install-plan.yaml"
            write_stage2_install_plan(plan, "containerd", "compute")

            verifier = ki2stage2.Verifier()
            ki2stage2.verify_stage2_install_plan(plan, "containerd", "compute", verifier)

            self.assertEqual(verifier.errors, [])

    def test_stage2_install_plan_rejects_wrong_runtime_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "install-plan.yaml"
            write_stage2_install_plan(plan, "containerd", "compute")
            text = plan.read_text(encoding="utf-8").replace("unix:///run/containerd/containerd.sock", "unix:///var/run/crio/crio.sock")
            plan.write_text(text, encoding="utf-8")

            verifier = ki2stage2.Verifier()
            ki2stage2.verify_stage2_install_plan(plan, "containerd", "compute", verifier)

            self.assertTrue(any("CRI socket" in item for item in verifier.errors))

    def test_install_plan_verifier_exposes_cli_command(self):
        parser = ki2stage2.build_parser()
        args = parser.parse_args(["verify-install-plan", "--plan", "/tmp/install-plan.yaml", "--runtime", "containerd", "--role", "compute"])
        self.assertEqual(args.func, ki2stage2.command_verify_install_plan)


if __name__ == "__main__":
    unittest.main()
