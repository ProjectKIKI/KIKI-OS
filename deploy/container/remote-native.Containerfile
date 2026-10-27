FROM docker.io/library/rockylinux@sha256:d644d203142cd5b54ad2a83a203e1dee68af2229f8fe32f52a30c6e1d3c3a9e0

RUN dnf install -y dnf-plugins-core && dnf config-manager --set-enabled crb \
 && dnf install -y --setopt=install_weak_deps=False \
 gcc gcc-c++ make cmake meson ninja-build pkgconf-pkg-config golang perl \
 python3 python3-devel python3-pip curl-minimal tar gzip xz bzip2 patch \
 diffutils findutils file git xorriso grub2-tools grub2-tools-extra \
 grub2-pc-modules grub2-efi-x64-modules grub2-efi-x64-cdboot mtools \
 cpio qemu-img openssl-devel zlib-devel expat-devel libcap-devel \
 libseccomp-devel libacl-devel libattr-devel bison flex gawk gettext \
 gperf bc elfutils-libelf-devel ncurses-devel rsync gnupg2 squashfs-tools \
 llvm-21.1.8-2.el9.x86_64 llvm-devel-21.1.8-2.el9.x86_64 \
 clang-21.1.8-2.el9.x86_64 lld-21.1.8-2.el9.x86_64 \
 && dnf clean all

COPY wheels/ /opt/kiki-host/cache/python/
COPY rust/ /opt/kiki-rust-dist/
COPY host-python.lock /opt/kiki-prep/host-python.lock
COPY rust-sources.json /opt/kiki-prep/rust-sources.json
COPY ki2buildenv.py /opt/kiki-prep/ki2buildenv.py
COPY prepare-image.py /opt/kiki-prep/prepare-image.py
COPY patchelf /opt/kiki-host/bin/patchelf
RUN chmod 0755 /opt/kiki-host/bin/patchelf && python3 -I -B /opt/kiki-prep/prepare-image.py

ENV PATH=/opt/kiki-host/venv/bin:/opt/kiki-host/rust-1.94.0/bin:/opt/kiki-host/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
 PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 \
 KIKI_TOOLCHAIN_ID=container-meson-1.9.2-llvm21-20261023 \
 CARGO_HOME=/candidate-work/cache/cargo HOME=/candidate-work/home \
 TMPDIR=/candidate-work/tmp XDG_CACHE_HOME=/candidate-work/cache/xdg
WORKDIR /work
EXPOSE 8090
ENTRYPOINT ["python3", "tools/ki2ci_candidate.py"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8090", "--repo-root", "/work", "--artifact-root", "/work/build/ki2ci", "--jobs", "2"]
