profile_kiki() {
	profile_standard
	title="KIKI Alpine Installer"
	desc="Minimal Alpine runtime for installing Debian-based KIKI nodes"
	profile_abbrev="kiki"
	image_ext="iso"
	arch="x86_64"
	kernel_flavors="lts"
	kernel_cmdline="nomodeset quiet"
	if [ "${KIKI_AUTOINSTALL:-0}" = "1" ]; then
		kernel_cmdline="$kernel_cmdline console=ttyS0,115200n8 kiki.autoinstall=1"
	fi
	syslinux_serial="0 115200"
	apkovl="${KIKI_APKOVL:-}"
	apks="$apks
		linux-lts=6.6.139-r0
		python3
		py3-yaml
		ca-certificates
		curl
		openssh
		debootstrap
		parted
		gptfdisk
		e2fsprogs
		dosfstools
		util-linux
		grub
		grub-bios
		grub-efi
		efibootmgr
	"

	if [ -z "$apkovl" ]; then
		echo "KIKI_APKOVL must point to installer/dist/kiki-alpine-overlay.tar.gz" >&2
		return 1
	fi
}
