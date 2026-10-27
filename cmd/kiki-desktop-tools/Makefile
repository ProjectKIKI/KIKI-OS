CC ?= cc
CFLAGS ?= -O2 -pipe -Wall -Wextra -Werror
PREFIX ?= /usr
GTK_CFLAGS := $(shell pkg-config --cflags gtk4)
GTK_LIBS := $(shell pkg-config --libs gtk4)

all: kiki-desktop-tools

kiki-desktop-tools: main.c
	$(CC) $(CFLAGS) $(GTK_CFLAGS) -o $@ $< $(LDFLAGS) $(GTK_LIBS)

install: kiki-desktop-tools
	install -Dm755 kiki-desktop-tools $(DESTDIR)$(PREFIX)/bin/kiki-desktop-tools
	install -Dm644 org.kiki.Files.desktop $(DESTDIR)$(PREFIX)/share/applications/org.kiki.Files.desktop
	install -Dm644 org.kiki.Settings.desktop $(DESTDIR)$(PREFIX)/share/applications/org.kiki.Settings.desktop
	install -Dm644 org.kiki.Terminal.desktop $(DESTDIR)$(PREFIX)/share/applications/org.kiki.Terminal.desktop

clean:
	rm -f kiki-desktop-tools
