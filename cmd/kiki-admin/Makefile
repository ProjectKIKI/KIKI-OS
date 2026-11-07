CC ?= cc
CFLAGS ?= -O2 -pipe -Wall -Wextra -Werror -fstack-protector-strong
PREFIX ?= /usr
PKGS = libadwaita-1 json-glib-1.0
FLAGS := $(shell pkg-config --cflags $(PKGS))
LIBS := $(shell pkg-config --libs $(PKGS))

all: kiki-admin
kiki-admin: main.c pixel.h
	$(CC) $(CFLAGS) $(FLAGS) -o $@ $< $(LDFLAGS) $(LIBS)
ui-test: ui_test.c main.c pixel.h
	$(CC) $(CFLAGS) $(FLAGS) -o $@ $< $(LDFLAGS) $(LIBS)
install: kiki-admin
	install -Dm755 kiki-admin $(DESTDIR)$(PREFIX)/bin/kiki-admin
	install -Dm755 ../../distro/sources/kiki-admin/usr/bin/kiki-adminctl $(DESTDIR)$(PREFIX)/bin/kiki-adminctl
	install -Dm755 ../../distro/sources/kiki-admin/usr/libexec/kiki-admin-helper $(DESTDIR)$(PREFIX)/libexec/kiki-admin-helper
	install -Dm755 ../../distro/sources/kiki-admin/usr/libexec/kiki-admin-backend.py $(DESTDIR)$(PREFIX)/libexec/kiki-admin-backend.py
	install -Dm644 ../../distro/sources/kiki-admin/usr/share/applications/org.kiki.Admin.desktop $(DESTDIR)$(PREFIX)/share/applications/org.kiki.Admin.desktop
	install -Dm644 ../../distro/sources/kiki-admin/usr/share/polkit-1/actions/org.kiki.admin.policy $(DESTDIR)$(PREFIX)/share/polkit-1/actions/org.kiki.admin.policy
	install -Dm644 ../../distro/sources/kiki-admin/usr/share/icons/hicolor/scalable/apps/org.kiki.Admin.svg $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/org.kiki.Admin.svg
clean:
	rm -f kiki-admin ui-test
