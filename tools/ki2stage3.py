#!/usr/bin/env python3
"""Stage 3 contract and kube reconcile verification for KIKI OS."""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:
    raise SystemExit("python3-yaml or PyYAML is required") from exc


class Stage3Error(RuntimeError):
    pass


def load_ki2build(repo_root: Path):
    path = repo_root / "tools/ki2build.py"
    spec = importlib.util.spec_from_file_location("ki2build_stage3", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage3Error(f"YAML document must be a map: {path}")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage3Error(message)


def verify_contract(repo_root: Path) -> dict[str, Any]:
    defaults_dir = repo_root / "distro/sources/kiki-agent/usr/share/kiki/defaults"
    profiles_dir = repo_root / "distro/sources/kiki-agent/usr/share/kiki/profiles"
    defaults = {name: load_yaml(defaults_dir / f"{name}.yaml") for name in ("system", "network", "kubernetes")}
    expected_profiles = {
        "server-core": ("none", "none"),
        "bootstrap": ("bootstrap-control-plane", "init"),
        "control": ("control-plane", "join"),
        "compute": ("compute", "join"),
    }
    for name, (role, action) in expected_profiles.items():
        profile = load_yaml(profiles_dir / f"{name}.yaml")
        kubernetes = profile.get("kubernetes", {})
        require(kubernetes.get("role") == role, f"{name}: Kubernetes role must be {role}")
        require(kubernetes.get("kubeadm", {}).get("action") == action, f"{name}: kubeadm action must be {action}")

    safety = defaults["system"].get("safety", {})
    require(safety.get("allow_cluster_reset") is False, "cluster reset must be denied by default")
    require(safety.get("allow_control_plane_cert_upload") is False, "certificate upload must be denied by default")
    require(safety.get("require_join_token") is True, "join token must be required")
    require(safety.get("require_ca_cert_hash") is True, "CA certificate hash must be required")
    cni = defaults["kubernetes"].get("kubernetes", {}).get("cni", {})
    require(cni.get("enabled") is False, "CNI auto-apply must be disabled by default")
    require(set(cni.get("allowed_providers", [])) == {"flannel", "calico", "cilium"}, "CNI allowlist is incomplete")

    ki2build = load_ki2build(repo_root)
    recipes = ki2build.load_recipes(repo_root / "distro/recipes")
    recipe = recipes.get("kiki-agent")
    require(recipe is not None, "kiki-agent recipe is missing")
    source_inputs = set(recipe.source.get("inputs", []))
    for required in ("go.mod", "vendor", "cmd/kiki-agent", "internal/stage3"):
        require(required in source_inputs, f"kiki-agent source input is missing: {required}")
    require(recipe.build.get("skip_sysroot") is True, "kiki-agent host Go build must explicitly skip target sysroot")
    commands = "\n".join(str(item) for item in recipe.build.get("compile", []))
    require("-mod=vendor" in commands and "-buildvcs=false" in commands, "kiki-agent build must use vendored reproducible inputs")
    ki2ctl_recipe = recipes.get("ki2ctl")
    require(ki2ctl_recipe is not None, "ki2ctl recipe is missing")
    require(
        set(ki2ctl_recipe.dependencies.get("runtime", [])) == {"python", "install-info"},
        "ki2ctl must include Python and the documentation index tool without a client-side crypto process dependency",
    )
    policy_path = repo_root / "distro/sources/ki2ctl/etc/ki2/policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    require(policy.get("require_repository_signature") is True, "installed repository policy must require signatures")
    require(policy.get("signature_algorithm") == "ed25519", "installed repository policy must require Ed25519")

    promoted_sources = {
        "bridge-utils": {
            "version": "1.7.1",
            "sha256": "a61d8be4f1a1405c60c8ef38d544f0c18c05b33b9b07e5b4b31033536165e60e",
        },
        "ethtool": {
            "version": "6.15",
            "sha256": "9477c365114d910120aaec5336a1d16196c833d8486f7c6da67bedef57880ade",
        },
        "chrony": {
            "version": "4.8",
            "sha256": "33ea8eb2a4daeaa506e8fcafd5d6d89027ed6f2f0609645c6f149b560d301706",
        },
        "conntrack-tools": {
            "version": "1.4.9",
            "sha256": "c15afe488a8d408c9d6d61e97dbd19f3c591942f62c13df6453a961ca4231cae",
        },
        "socat": {
            "version": "1.8.1.3",
            "sha256": "25bc6476292b2e614220989c77b0b6fca87bb2525d9747b31a6639b1fb602418",
        },
        "iptables": {
            "version": "1.8.13",
            "sha256": "1afcd33da9e8f913ace6a2126788162e207e26f5d5e29c6573c0e581ffc58b99",
        },
        "nftables": {
            "version": "1.1.6",
            "sha256": "372931bda8556b310636a2f9020adc710f9bab66f47efe0ce90bff800ac2530c",
        },
        "firewalld": {
            "version": "2.5.1",
            "sha256": "50fd01cf0b696a1cb7ca722e972d6173b0c5aa6ab13892b00842ae52172b081e",
        },
    }
    for name, expected in promoted_sources.items():
        promoted = recipes.get(name)
        require(promoted is not None, f"promoted source recipe is missing: {name}")
        require(promoted.version == expected["version"], f"{name}: unexpected source version")
        require(promoted.source.get("type") == "url", f"{name}: source must be a pinned URL")
        require(promoted.source.get("sha256") == expected["sha256"], f"{name}: source hash is not pinned")
        require(promoted.build.get("system") != "host-files", f"{name}: source promotion regressed to host-files")

    socat = recipes["socat"]
    socat_options = set(socat.build.get("configure_options", []))
    require({"--disable-readline", "--disable-libwrap"} <= socat_options, "socat undeclared optional libraries must be disabled")
    require("--disable-openssl" not in socat_options, "socat TLS support must remain enabled")
    require(socat.build.get("env", {}).get("SOURCE_DATE_EPOCH") == "1782453234", "socat build timestamp must be reproducible")
    bridge_utils = recipes["bridge-utils"]
    bridge_commands = "\n".join(
        str(command)
        for phase in ("configure", "compile", "install")
        for command in bridge_utils.build.get(phase, [])
    )
    require("PACKAGE_VERSION=\"1.7.1\"" in bridge_commands, "bridge-utils must build the real versioned brctl")
    require("/usr/sbin/brctl" in bridge_commands, "bridge-utils must install brctl")
    require("/usr/sbin/bridge" not in bridge_commands, "iproute2 must remain the sole owner of the bridge command")
    conntrack = recipes["conntrack-tools"]
    require(
        conntrack.dependencies.get("runtime", [])
        == ["glibc", "libmnl", "libnfnetlink", "libnetfilter-conntrack"],
        "conntrack runtime library stack is incomplete",
    )
    require(conntrack.build.get("sysroot_exclude") == ["glibc"], "conntrack must consume KIKI netfilter libraries from its sysroot")
    conntrack_options = set(conntrack.build.get("configure_options", []))
    require({"--disable-cthelper", "--disable-cttimeout"} <= conntrack_options, "conntrack CLI-only build boundary is not explicit")
    for library in ("libmnl", "libnfnetlink", "libnetfilter-conntrack"):
        dependency = recipes.get(library)
        require(dependency is not None, f"conntrack source dependency is missing: {library}")
        require(dependency.source.get("type") == "url", f"{library}: source must be pinned")
        require(dependency.build.get("system") != "host-files", f"{library}: host library copy is forbidden")
    netfilter_conntrack = recipes["libnetfilter-conntrack"]
    require(int(netfilter_conntrack.release) >= 2, "libnetfilter-conntrack package must sanitize pkg-config paths")
    netfilter_install = "\n".join(str(command) for command in netfilter_conntrack.build.get("install", []))
    require("libnetfilter_conntrack.pc" in netfilter_install and "KI2_SYSROOT" in netfilter_install, "libnetfilter_conntrack pkg-config cleanup is missing")

    nft_support = {
        "gmp": ("6.3.0", "a3c2b80201b89e68616f4ad30bc66aee4927c3ce50e33929ca819d5c43538898"),
        "jansson": ("2.15.0", "070a629590723228dc3b744ae90e965a569efb9c535b3309b52e80e75d8eb3be"),
        "readline": ("8.3", "fe5383204467828cd495ee8d1d3c037a7eba1389c22bc6a041f627976f9061cc"),
        "libnftnl": ("1.3.1", "607da28dba66fbdeccf8ef1395dded9077e8d19f2995f9a4d45a9c2f0bcffba8"),
    }
    for name, (version, sha256) in nft_support.items():
        dependency = recipes.get(name)
        require(dependency is not None, f"nftables source dependency is missing: {name}")
        require(dependency.version == version, f"{name}: unexpected source version")
        require(dependency.source.get("type") == "url", f"{name}: source must be a pinned URL")
        require(dependency.source.get("sha256") == sha256, f"{name}: source hash is not pinned")
        require(dependency.build.get("system") != "host-files", f"{name}: host library copy is forbidden")
    require(int(recipes["readline"].release) >= 2, "readline package must omit the redundant /usr/lib RPATH")
    readline_commands = "\n".join(
        str(command)
        for phase in ("configure", "compile", "install")
        for command in recipes["readline"].build.get(phase, [])
    )
    require("-Wl,-rpath,$(libdir)" in readline_commands, "readline RPATH cleanup is missing")

    iptables = recipes["iptables"]
    iptables_options = set(iptables.build.get("configure_options", []))
    require(
        {"--enable-nftables", "--enable-libnfnetlink", "--enable-connlabel", "--disable-static", "--enable-shared"}
        <= iptables_options,
        "iptables nft feature boundary is incomplete",
    )
    require(
        iptables.dependencies.get("runtime", [])
        == ["glibc", "libmnl", "libnfnetlink", "libnetfilter-conntrack", "libnftnl"],
        "iptables runtime library stack is incomplete or cyclic",
    )
    iptables_install = "\n".join(str(command) for command in iptables.build.get("install", []))
    require("../sbin/xtables-legacy-multi" in iptables_install, "iptables-xml must use a safe relative link")
    require("xtables-nft-multi" in iptables_install, "iptables default commands must select the nft backend")

    nftables = recipes["nftables"]
    nftables_options = set(nftables.build.get("configure_options", []))
    require(
        {"--disable-debug", "--with-cli=readline", "--with-json", "--with-xtables"} <= nftables_options,
        "nftables production feature boundary is incomplete",
    )
    require(
        nftables.dependencies.get("runtime", [])
        == ["glibc", "gmp", "jansson", "readline", "libmnl", "libnftnl", "iptables"],
        "nftables runtime library stack is incomplete",
    )
    require("glibc" not in nftables.build.get("sysroot_exclude", []), "nftables must include target glibc with its target GMP")
    nftables_env = nftables.build.get("env", {})
    require(
        "--sysroot=${KI2_SYSROOT}" in str(nftables_env.get("CC", ""))
        and "--sysroot=${KI2_SYSROOT}" in str(nftables_env.get("LDFLAGS", "")),
        "nftables must compile and link with the target sysroot",
    )
    nftables_install = "\n".join(str(command) for command in nftables.build.get("install", []))
    require(
        all(path in nftables_install for path in ("py/src/__init__.py", "py/src/nftables.py", "py/src/schema.json")),
        "nftables Python binding payload is incomplete",
    )

    firewalld = recipes["firewalld"]
    firewalld_options = set(firewalld.build.get("configure_options", []))
    require(
        {"--disable-nls", "--disable-schemas-compile", "--with-systemd-unitdir=/usr/lib/systemd/system"}
        <= firewalld_options,
        "firewalld server build boundary is incomplete",
    )
    firewalld_commands = "\n".join(
        str(command)
        for phase in ("configure", "compile", "install")
        for command in firewalld.build.get(phase, [])
    )
    require("distro/scripts/intltool-minimal" in firewalld_commands, "firewalld deterministic metadata tool is missing")
    require("python3.12/site-packages/firewall" in firewalld_commands, "firewalld Python modules must target KIKI Python")
    require("SUBDIRS=icons" in firewalld_commands, "firewalld build must exclude upstream test generation")
    require("firewall-applet" in firewalld_commands and "firewall-config" in firewalld_commands, "firewalld GUI split is not explicit")

    firewall_runtime_sources = {
        "dbus": ("1.14.10", "ba1f21d2bd9d339da2d4aa8780c09df32fea87998b73da24f49ab9df1e36a50f"),
        "glib": ("2.84.4", "8a9ea10943c36fc117e253f80c91e477b673525ae45762942858aef57631bb90"),
        "gobject-introspection": ("1.84.0", "945b57da7ec262e5c266b89e091d14be800cc424277d82a02872b7d794a84779"),
        "python": ("3.12.4", "01b3c1c082196f3b33168d344a9c85fb07bfe0e7ecfe77fee4443420d1ce2ad9"),
        "python-setuptools": ("84.0.0", "f4695c21257f0d9b537ec2692c941d02ee143b7cc1276941349a546573b2ef73"),
        "python3-dbus": ("1.4.0", "c36b28f10ffcc8f1f798aca973bcc132f91f33eb9b6b8904381b4077766043d5"),
        "python3-gobject": ("3.52.3", "00e427d291e957462a8fad659a9f9c8be776ff82a8b76bdf402f1eaeec086d82"),
    }
    for name, (version, sha256) in firewall_runtime_sources.items():
        dependency = recipes.get(name)
        require(dependency is not None, f"firewalld runtime source recipe is missing: {name}")
        require(dependency.version == version, f"{name}: unexpected firewalld runtime source version")
        require(dependency.source.get("type") == "url", f"{name}: runtime source must be a pinned URL")
        require(dependency.source.get("sha256") == sha256, f"{name}: runtime source hash is not pinned")
        require(dependency.build.get("system") != "host-files", f"{name}: host runtime copy is forbidden")

    hardened_foundation_releases = {
        "zlib": 3,
        "expat": 3,
        "openssl": 5,
        "xz": 3,
        "python": 5,
        "python-setuptools": 2,
        "python3-dbus": 3,
        "python3-gobject": 3,
        "firewalld": 10,
    }
    for name, minimum_release in hardened_foundation_releases.items():
        require(
            int(recipes[name].release) >= minimum_release,
            f"{name}: Stage 3 runtime hardening release is missing",
        )
    for name in ("zlib", "expat", "openssl", "xz", "python"):
        install_commands = "\n".join(str(command) for command in recipes[name].build.get("install", []))
        require("-name '*.a' -delete" in install_commands, f"{name}: static runtime archive cleanup is missing")

    require(int(recipes["dbus"].release) >= 7, "D-Bus package must include the RPATH-clean build revision")
    dbus_commands = "\n".join(
        str(command)
        for phase in ("configure", "compile", "install")
        for command in recipes["dbus"].build.get(phase, [])
    )
    require("hardcode_libdir_flag_spec" in dbus_commands, "D-Bus libtool RPATH suppression is missing")
    require("strip --strip-unneeded" in dbus_commands, "D-Bus installed ELF cleanup is missing")

    introspection = recipes["gobject-introspection"]
    require(int(introspection.release) >= 6, "GObject Introspection package must include GLib typelibs")
    introspection_commands = "\n".join(
        str(command)
        for phase in ("configure", "compile", "install")
        for command in introspection.build.get(phase, [])
    )
    require("-Dintrospection=enabled" in introspection_commands, "GLib typelib second-stage build is missing")
    require("girepository-1.0" in introspection_commands, "GObject typelib installation is missing")
    extra_sources = introspection.source.get("extra", [])
    require(
        any(item.get("file") == "glib-2.84.4.tar.xz" and item.get("sha256") == firewall_runtime_sources["glib"][1] for item in extra_sources),
        "GObject Introspection GLib source input is not pinned",
    )

    require(
        recipes["python3-dbus"].dependencies.get("runtime", []) == ["dbus", "glib", "python"],
        "python3-dbus runtime dependency stack is incomplete",
    )
    require(
        recipes["python3-gobject"].dependencies.get("runtime", [])
        == ["glib", "gobject-introspection", "libffi", "python"],
        "python3-gobject runtime dependency stack is incomplete",
    )
    require(
        firewalld.dependencies.get("runtime", [])
        == ["dbus", "glib", "gobject-introspection", "nftables", "python", "python3-dbus", "python3-gobject", "systemd"],
        "firewalld runtime dependency stack is incomplete",
    )
    for script in ("ki2-target-python3", "ki2-target-pkg-config", "ki2-target-g-ir-scanner"):
        require((repo_root / "distro/scripts" / script).is_file(), f"target build wrapper is missing: {script}")

    host_file_recipes = sorted(name for name, item in recipes.items() if item.build.get("system") == "host-files")
    require(not host_file_recipes, f"host-files recipes remain: {', '.join(host_file_recipes)}")

    passwd = (repo_root / "distro/sources/base-files/etc/passwd").read_text(encoding="utf-8").splitlines()
    group = (repo_root / "distro/sources/base-files/etc/group").read_text(encoding="utf-8").splitlines()
    tmpfiles = (repo_root / "distro/sources/base-files/usr/lib/tmpfiles.d/kiki.conf").read_text(encoding="utf-8")
    require("chrony:x:998:998:Chrony time synchronization:/var/lib/chrony:/usr/sbin/nologin" in passwd, "chrony system user is missing")
    require("chrony:x:998:" in group, "chrony system group is missing")
    require("/run/chrony 0755 chrony chrony" in tmpfiles, "chrony runtime directory ownership is missing")
    require("/var/lib/chrony 0750 chrony chrony" in tmpfiles, "chrony state directory ownership is missing")
    matrix_example = load_yaml(repo_root / "distro/specs/kiki-stage3-vm-matrix.example.yaml")
    require(matrix_example.get("schema") == "kiki-stage3-vm-matrix-v1", "Stage 3 VM matrix example is invalid")
    require((repo_root / "tools/ki2stage3vm.py").is_file(), "Stage 3 VM matrix runner is missing")

    management_console = repo_root / "tools/kiki_console.py"
    require(management_console.is_file(), "Stage 3 management console is missing")
    package_groups_path = repo_root / "distro/sources/ki2ctl/usr/share/ki2/package-groups.json"
    require(package_groups_path.is_file(), "package group catalog is missing")
    package_groups = json.loads(package_groups_path.read_text(encoding="utf-8"))
    require(package_groups.get("schema") == "ki2-package-groups-v1", "package group schema is invalid")
    package_group_ids = {
        item.get("id") for item in package_groups.get("groups", []) if isinstance(item, dict)
    }
    require(
        {"minimal", "server", "ai-console", "container-containerd", "container-crio", "kubernetes-node"}
        <= package_group_ids,
        "required package groups are incomplete",
    )
    ki2ctl_source = (repo_root / "distro/sources/ki2ctl/usr/bin/ki2ctl").read_text(encoding="utf-8")
    require(
        "command_group_install" in ki2ctl_source
        and "command_group_remove" in ki2ctl_source
        and "reasons" in ki2ctl_source,
        "ki2ctl package group lifecycle or install-reason tracking is missing",
    )
    installer_tui_source = (repo_root / "cmd/kiki-installer-tui/main.go").read_text(encoding="utf-8")
    installer_gtk_source = (repo_root / "cmd/kiki-installer-gtk/main.c").read_text(encoding="utf-8")
    require("Groups" in installer_tui_source and "group add|remove" in installer_tui_source, "TUI package group selection is missing")
    require('"--groups"' in installer_gtk_source, "GTK package group selection is missing")
    systemd_recipe = recipes.get("systemd")
    ai_recipe = recipes.get("kiki-ai-console")
    llama_recipe = recipes.get("llama-cpp")
    libstdcxx_recipe = recipes.get("libstdcxx")
    model_recipe = recipes.get("kiki-ops-model")
    require(systemd_recipe is not None, "systemd runtime recipe is missing")
    require(
        "-Dmachined=true" in systemd_recipe.build.get("configure_options", []),
        "systemd-machined must remain enabled for the managed AI runtime",
    )
    require(ai_recipe is not None, "on-device AI console recipe is missing")
    require(llama_recipe is not None, "llama.cpp runtime recipe is missing")
    require(libstdcxx_recipe is not None, "KIKI C++ runtime recipe is missing")
    require(model_recipe is not None, "bundled GGUF model recipe is missing")
    require(
        model_recipe.source.get("sha256") == "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e",
        "bundled GGUF model digest is not pinned",
    )
    model_extras = model_recipe.source.get("extra", [])
    require(
        len(model_extras) == 1
        and model_extras[0].get("sha256") == "832dd9e00a68dd83b3c3fb9f5588dad7dcf337a0db50f7d9483f310cd292e92e",
        "bundled GGUF model license digest is not pinned",
    )
    require(
        libstdcxx_recipe.source.get("sha256") == "a6e21868ead545cf87f0c01f84276e4b5281d672098591c1c896241f09363478",
        "GNU C++ runtime source digest is not pinned",
    )
    libstdcxx_commands = "\n".join(
        str(command)
        for phase in ("prepare", "configure", "compile", "install")
        for command in libstdcxx_recipe.build.get(phase, [])
    )
    require("-lgcc -lgcc_eh" in libstdcxx_commands, "GNU C++ runtime must not require an unowned host libgcc_s")
    require("gthr-default.h" in libstdcxx_commands and "--enable-libstdcxx-threads=yes" in libstdcxx_commands, "GNU C++ runtime must provide the POSIX thread symbols used by llama.cpp")
    require(
        llama_recipe.source.get("sha256") == "bd13fa381488aa59ae4081aca24d368a956ad6e393c54931510a94d240590e33",
        "llama.cpp source digest is not pinned",
    )
    require(llama_recipe.build.get("system") == "cmake", "llama.cpp must be built from source")
    llama_commands = "\n".join(
        str(command)
        for phase in ("configure", "compile", "install")
        for command in llama_recipe.build.get(phase, [])
    )
    require("LLAMA_USE_PREBUILT_UI=OFF" in llama_commands, "llama.cpp build must not fetch UI assets")
    require("KI2_SYSROOT_LDFLAGS" in llama_commands, "llama.cpp must link against the packaged KIKI C++ runtime")
    require("libstdc++.so.6.0.29" in llama_commands, "llama.cpp package must carry its source-built C++ runtime")
    require("kiki-ops-model" in llama_recipe.dependencies.get("build", []), "llama.cpp must build against the verified GGUF model package")
    require(
        "llama-cpp" not in ai_recipe.dependencies.get("runtime", []),
        "AI console must allow remote mode without forcing the local llama.cpp runtime",
    )
    require("/var/lib/kiki/models/kiki-ops.gguf" in llama_commands, "llama.cpp package must carry the verified GGUF model")
    require(
        set(ai_recipe.source.get("inputs", [])) >= {"go.mod", "vendor", "cmd/kiki-ai-console", "internal/aiconsole"},
        "AI console reproducible Go inputs are incomplete",
    )
    for required in (
        "distro/sources/kiki-ai-console/etc/systemd/system/kiki-ai-console@.service",
        "distro/sources/kiki-ai-console/etc/systemd/system/kiki-llama-server.service",
        "distro/sources/kiki-ai-console/etc/kiki/ai-console.json",
        "distro/sources/kiki-ai-console/usr/libexec/kiki-llama-runtime",
        "distro/sources/kiki-ai-console/var/lib/machines/kiki-ai/etc/os-release",
    ):
        require((repo_root / required).is_file(), f"AI console asset is missing: {required}")
    llama_unit = (repo_root / "distro/sources/kiki-ai-console/etc/systemd/system/kiki-llama-server.service").read_text(encoding="utf-8")
    llama_launcher = (repo_root / "distro/sources/kiki-ai-console/usr/libexec/kiki-llama-runtime").read_text(encoding="utf-8")
    console_unit = (repo_root / "distro/sources/kiki-ai-console/etc/systemd/system/kiki-ai-console@.service").read_text(encoding="utf-8")
    require("/usr/libexec/kiki-llama-runtime" in llama_unit, "llama.cpp service must use the isolated runtime launcher")
    require(
        "systemd-nspawn" in llama_launcher
        and "--register=yes" in llama_launcher
        and "--bind-ro=/usr" in llama_launcher,
        "llama.cpp runtime must prefer a machinectl-managed systemd-nspawn lightweight container",
    )
    require("--wait-local-runtime=90s" in console_unit, "tty1 AI console must wait for the local runtime readiness check")
    profile_paths = [repo_root / "distro/profiles/server-core.toml", *sorted((repo_root / "distro/profiles").glob("kiki-kube-*.yaml"))]
    for profile_path in profile_paths:
        profile = ki2build.load_profile(profile_path)
        services = set(profile.get("services", {}).get("enable", []))
        require("kiki-ai-console" in profile.get("packages", []), f"{profile_path.name}: AI console package is missing")
        require("llama-cpp" in profile.get("packages", []), f"{profile_path.name}: local llama.cpp runtime is missing")
        require("kiki-kmscon" in profile.get("packages", []), f"{profile_path.name}: Korean console runtime is missing")
        require("kiki-ai-console-kmscon@tty1.service" in services, f"{profile_path.name}: tty1 Korean AI console is missing")
        require("getty@tty2.service" in services, f"{profile_path.name}: tty2 recovery shell is missing")
        require("getty@tty1.service" not in services, f"{profile_path.name}: tty1 getty conflicts with the AI console")
    server_profile = ki2build.load_profile(repo_root / "distro/profiles/server-core.toml")
    require(
        server_profile.get("groups") == ["server", "ai-console", "installer-gui"],
        "server-core must include the graphical installer package group",
    )
    require("kiki-installer-gtk" in server_profile.get("packages", []), "server-core graphical installer package is missing")
    os_build_plan = load_yaml(repo_root / "distro/build-plans/stage3-server-core.yaml")
    require(os_build_plan.get("schema") == "kiki-os-build-plan-v1", "Stage 3 OS build plan schema is invalid")
    require(os_build_plan.get("name") == "stage3-server-core", "Stage 3 OS build plan name is invalid")
    require(os_build_plan.get("build", {}).get("profile") == "distro/profiles/server-core.toml", "Stage 3 build plan must use server-core")
    require(os_build_plan.get("graphics", {}).get("enabled") is True, "Stage 3 GTK/Wayland runtime preparation is disabled")
    require(os_build_plan.get("repository", {}).get("algorithm") == "ed25519", "Stage 3 repository must use Ed25519")
    require(os_build_plan.get("verify", {}).get("stage3_contract") is True, "Stage 3 contract gate is missing from the OS build plan")
    require(os_build_plan.get("iso", {}).get("enabled") is False, "Stage 3 ISO build must require explicit activation")

    wrapper = (repo_root / "distro/sources/kiki-agent/usr/bin/kiki-agent").read_text(encoding="utf-8")
    kubeadm = (repo_root / "distro/sources/kiki-kubeadm/usr/bin/kiki-kubeadm").read_text(encoding="utf-8")
    require('"kube", "reconcile"' in wrapper and '"plan", "fetch"' in wrapper, "compatibility wrapper does not delegate Stage 3 commands")
    require("--token-file" in kubeadm, "kiki-kubeadm must accept token references")
    return {
        "defaults": 3,
        "profiles": len(expected_profiles),
        "recipe": recipe.package_id,
        "source_promotions": sorted(promoted_sources),
        "firewall_runtime_sources": sorted(firewall_runtime_sources),
        "hardened_foundation_releases": hardened_foundation_releases,
        "management_console": "tools/kiki_console.py",
        "on_device_ai_console": "tty1",
        "bundled_model": "Qwen2.5-1.5B-Instruct-Q4_K_M",
        "recovery_shell": "tty2",
        "host_file_recipes": host_file_recipes,
    }


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    print("[run] " + " ".join(command))
    merged = os.environ.copy()
    if env:
        merged.update(env)
    result = subprocess.run(command, cwd=cwd, env=merged, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise Stage3Error(f"command failed: {' '.join(command)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


def smoke_reconcile(repo_root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="kiki-stage3-smoke-") as tmp:
        root = Path(tmp) / "root"
        binary = Path(tmp) / "kiki-agent-stage3"
        (root / "usr/share/kiki").mkdir(parents=True)
        shutil.copytree(repo_root / "distro/sources/kiki-agent/usr/share/kiki/defaults", root / "usr/share/kiki/defaults")
        shutil.copytree(repo_root / "distro/sources/kiki-agent/usr/share/kiki/profiles", root / "usr/share/kiki/profiles")
        (root / "var/lib/ki2").mkdir(parents=True)
        shutil.copy2(repo_root / "distro/install-plans/kiki-kube-compute.yaml", root / "var/lib/ki2/install-plan.yaml")
        (root / "etc/kubernetes/kiki").mkdir(parents=True)
        shutil.copy2(
            repo_root / "distro/sources/kube-node-config/etc/kubernetes/kiki/kubeadm-join-compute.yaml",
            root / "etc/kubernetes/kiki/kubeadm-join-compute.yaml",
        )
        token = "abcdef.0123456789abcdef"
        token_file = root / "run/secrets/kubeadm-token"
        token_file.parent.mkdir(parents=True)
        token_file.write_text(token + "\n", encoding="utf-8")
        run(
            ["go", "build", "-mod=vendor", "-buildvcs=false", "-o", str(binary), "./cmd/kiki-agent"],
            cwd=repo_root,
            env={"GOCACHE": str(Path(tmp) / "go-cache")},
        )
        result = run(
            [
                str(binary),
                "kube",
                "reconcile",
                "--root",
                str(root),
                "--kiki-kubeadm",
                str(repo_root / "distro/sources/kiki-kubeadm/usr/bin/kiki-kubeadm"),
                "--token-file",
                "/run/secrets/kubeadm-token",
                "--endpoint",
                "10.0.0.10:6443",
                "--ca-cert-hash",
                "sha256:" + "a" * 64,
                "--node-name",
                "worker-01",
                "--dry-run",
                "--skip-preflight",
            ],
            cwd=repo_root,
        )
        require(token not in result.stdout and token not in result.stderr, "join token leaked into process output")
        state = json.loads((root / "var/lib/kiki/kubernetes/state.json").read_text(encoding="utf-8"))
        require(state.get("status") == "dry-run" and state.get("action") == "join", "compute join dry-run state is invalid")
        rendered = (root / "var/lib/kiki/rendered/stage3-plan.yaml").read_text(encoding="utf-8")
        require("token_ref: /run/secrets/kubeadm-token" in rendered, "rendered plan did not preserve token reference")
        require(token not in rendered, "rendered plan contains plaintext join token")
        return {"role": state.get("role"), "action": state.get("action"), "status": state.get("status")}


def smoke_repository_signature(repo_root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="kiki-stage3-repo-signature-") as tmp:
        base = Path(tmp)
        packages = base / "repository/packages/x86_64"
        repository = base / "repository/repo"
        iso = base / "repository/iso"
        private_key = base / "keys/stage3-repo.ed25519"
        public_key = base / "keys/stage3-repo.ed25519.pub"
        target = base / "target"
        for path in (packages, repository, iso):
            path.mkdir(parents=True)
        # Exercise a real nonempty signed index, independently of built artifacts.
        fixture = {
            "name": "stage3-signature-probe", "version": "1", "release": "1",
            "arch": "x86_64", "license": "MIT", "tier": "test",
            "dependencies": {"build": [], "runtime": []}, "payload": {"file_count": 1},
        }
        with tarfile.open(packages / "stage3-signature-probe-1-1.x86_64.ki2", "w:gz") as archive:
            for name, data in (
                ("manifest.json", json.dumps(fixture).encode("utf-8")),
                ("rootfs/usr/share/kiki/signature-probe.txt", b"Stage 3 signature smoke\n"),
            ):
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                entry.mode = 0o644
                archive.addfile(entry, io.BytesIO(data))
        common = [
            sys.executable,
            "tools/ki2repo.py",
            "--packages-dir",
            str(packages),
            "--repo-dir",
            str(repository),
            "--iso-dir",
            str(iso),
        ]
        run(
            [
                *common,
                "keygen-ed25519",
                "--private-key",
                str(private_key),
                "--public-key",
                str(public_key),
            ],
            cwd=repo_root,
        )
        run(
            [
                *common,
                "generate",
                "--include-all-staged",
                "--channel",
                "stage3-v3",
                "--sign-key",
                str(private_key),
                "--sign-algorithm",
                "ed25519",
            ],
            cwd=repo_root,
        )
        run([*common, "verify", "--key", str(public_key)], cwd=repo_root)

        trust = target / "etc/ki2/trust"
        trust.mkdir(parents=True)
        shutil.copy2(public_key, trust / "stage3-repo.ed25519.pub")
        shutil.copy2(repo_root / "distro/sources/ki2ctl/etc/ki2/policy.json", target / "etc/ki2/policy.json")
        ki2ctl = repo_root / "distro/sources/ki2ctl/usr/bin/ki2ctl"
        run([sys.executable, str(ki2ctl), "--root", str(target), "repo", "set", str(base / "repository")], cwd=repo_root)
        update = run([sys.executable, str(ki2ctl), "--root", str(target), "update"], cwd=repo_root)
        require("metadata verified" in update.stdout, "ki2ctl did not verify Ed25519 repository metadata")
        metadata = json.loads((repository / "metadata.x86_64.json").read_text(encoding="utf-8"))
        return {
            "algorithm": metadata.get("security", {}).get("algorithm"),
            "key_id": metadata.get("security", {}).get("key_id"),
            "policy_enforced": True,
        }


def verify(repo_root: Path) -> dict[str, Any]:
    contract = verify_contract(repo_root)
    smoke = smoke_reconcile(repo_root)
    repository_signature = smoke_repository_signature(repo_root)
    run([sys.executable, "tools/ki2build.py", "validate", "--profile", "distro/profiles/server-core.toml", "--max-packages", "72"], cwd=repo_root)
    run(["go", "test", "-mod=vendor", "./internal/stage3", "./cmd/kiki-agent", "./internal/aiconsole", "./cmd/kiki-ai-console"], cwd=repo_root, env={"GOCACHE": str(Path(tempfile.gettempdir()) / "kiki-stage3-verify-go-cache")})
    return {"contract": contract, "smoke": smoke, "repository_signature": repository_signature}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify KIKI OS Stage 3 contracts and dry-run integration")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("command", choices=["contract", "verify"], nargs="?", default="verify")
    args = parser.parse_args(argv)
    try:
        result = verify_contract(args.repo_root.resolve()) if args.command == "contract" else verify(args.repo_root.resolve())
    except (OSError, Stage3Error, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
