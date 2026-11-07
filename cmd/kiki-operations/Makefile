CC ?= cc
CFLAGS ?= -O2 -pipe -Wall -Wextra -Werror -fstack-protector-strong
PKGS = gtk4 json-glib-1.0
FLAGS := $(shell pkg-config --cflags $(PKGS))
LIBS := $(shell pkg-config --libs $(PKGS))
all: kiki-operations
kiki-operations: main.c connections.h incident.h
	$(CC) $(CFLAGS) $(FLAGS) -o $@ $< $(LDFLAGS) $(LIBS)
ui-test: ui_test.c main.c connections.h incident.h
	$(CC) $(CFLAGS) $(FLAGS) -o $@ $< $(LDFLAGS) $(LIBS)
install: kiki-operations
	install -Dm755 kiki-operations $(DESTDIR)/usr/bin/kiki-operations
	cp -a ../../distro/sources/kiki-operations/. $(DESTDIR)/
	chmod 755 $(DESTDIR)/usr/bin/kiki-operationsctl $(DESTDIR)/usr/libexec/kiki-operations-backend.py $(DESTDIR)/usr/libexec/kiki-operations-console
clean:
	rm -f kiki-operations ui-test
.PHONY: all install clean
