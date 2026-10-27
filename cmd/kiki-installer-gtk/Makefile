CC ?= cc
CFLAGS ?= -O2 -pipe -Wall -Wextra -Werror
PREFIX ?= /usr
BRAND_ICON ?= ../../assets/brand/kikios-kiki-wordmark-v1.png

GTK_CFLAGS := $(shell pkg-config --cflags gtk4)
GTK_LIBS := $(shell pkg-config --libs gtk4)

.PHONY: all clean install

all: kiki-installer-gtk

kiki-installer-gtk: main.c network.h disk.h
	$(CC) $(CFLAGS) $(GTK_CFLAGS) -o $@ $< $(GTK_LIBS)

install: kiki-installer-gtk
	install -Dm755 kiki-installer-gtk $(DESTDIR)$(PREFIX)/bin/kiki-installer-gtk
	install -Dm644 style.css $(DESTDIR)$(PREFIX)/share/kiki-installer-gtk/style.css
	install -Dm644 $(BRAND_ICON) $(DESTDIR)$(PREFIX)/share/pixmaps/kiki-installer.png

clean:
	rm -f kiki-installer-gtk
