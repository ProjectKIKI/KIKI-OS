GO ?= go
PREFIX ?= /usr
OUTPUT ?= kiki-installer-gotk
LIVE ?= false
.PHONY: all test install clean
all:
	GOMAXPROCS=2 $(GO) build -mod=readonly -p 1 -tags gtk -ldflags "-X main.defaultLive=$(LIVE)" -o $(OUTPUT) .
test:
	$(GO) test -mod=readonly ./...
install: all
	install -Dm755 $(OUTPUT) $(DESTDIR)$(PREFIX)/bin/kiki-installer-gotk
clean:
	rm -f kiki-installer-gotk
