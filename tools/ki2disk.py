"""GPT partition writer for the installer; accepts only an unused whole block device."""
import argparse
import fcntl
import os
import stat
import struct
import subprocess
from pathlib import Path

MIB = 1024 * 1024
ESP = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
SWAP = "0657FD6D-A4AB-43C4-84E5-0933C84B4F4F"
LINUX = "0FC63DAF-8483-4772-8E79-3D69D8477DE4"


def partition_script(total_bytes, sector_size, esp_mib, swap_mib):
    if sector_size not in (512, 1024, 2048, 4096) or total_bytes % sector_size:
        raise ValueError("unsupported logical sector geometry")
    if esp_mib < 512 or swap_mib < 0:
        raise ValueError("invalid ESP or swap size")
    unit = MIB // sector_size
    start = unit
    parts = [(esp_mib * unit, ESP, "KIKI_EFI")]
    if swap_mib:
        parts.append((swap_mib * unit, SWAP, "KIKI_SWAP"))
    root_size = (total_bytes // MIB - 2 - esp_mib - swap_mib) * unit
    if root_size < 2048 * unit:
        raise ValueError("root partition must have at least 2 GiB")
    parts.append((root_size, LINUX, "KIKI_ROOT"))
    lines = ["label: gpt", "unit: sectors", ""]
    for size, kind, name in parts:
        lines.append(f'start={start}, size={size}, type={kind}, name="{name}"')
        start += size
    return "\n".join(lines) + "\n"


def require_unused_disk(path):
    info = path.stat()
    if not stat.S_ISBLK(info.st_mode):
        raise ValueError("target is not a block device")
    sysdev = Path(f"/sys/dev/block/{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}").resolve(strict=True)
    if (sysdev / "partition").exists():
        raise ValueError("target must be a whole disk")
    devices = [sysdev] + [p for p in sysdev.iterdir() if (p / "partition").is_file()]
    identities = {(p / "dev").read_text().strip() for p in devices}
    for p in devices:
        if any((p / "holders").iterdir()):
            raise ValueError("target or partition has active device-mapper/RAID holders")
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        if line.split()[2] in identities:
            raise ValueError("target or partition is mounted")
    for line in Path("/proc/swaps").read_text().splitlines()[1:]:
        swap = Path(line.split()[0])
        swap_info = swap.stat()
        device = swap_info.st_rdev if stat.S_ISBLK(swap_info.st_mode) else swap_info.st_dev
        if f"{os.major(device)}:{os.minor(device)}" in identities:
            raise ValueError("target contains active swap")
    return info.st_rdev


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disk", type=Path, required=True)
    parser.add_argument("--esp-mib", type=int, required=True)
    parser.add_argument("--swap-mib", type=int, required=True)
    args = parser.parse_args()
    try:
        disk = args.disk.resolve(strict=True)
        identity = require_unused_disk(disk)
        with disk.open("rb", buffering=0) as stream:
            if os.fstat(stream.fileno()).st_rdev != identity:
                raise ValueError("disk identity changed")
            sector = struct.unpack("I", fcntl.ioctl(stream, 0x1268, bytes(4)))[0]
            total = struct.unpack("Q", fcntl.ioctl(stream, 0x80081272, bytes(8)))[0]
        script = partition_script(total, sector, args.esp_mib, args.swap_mib)
        subprocess.run(["/sbin/sfdisk", "--lock=yes", "--wipe=always", str(disk)],
                       input=script, text=True, check=True)
        subprocess.run(["/sbin/sfdisk", "--verify", str(disk)], check=True)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"GPT partitioning failed: {exc}\n")


if __name__ == "__main__":
    main()
