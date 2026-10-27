//go:build gtk

package main

import (
	"github.com/diamondburned/gotk4/pkg/gio/v2"
	"github.com/diamondburned/gotk4/pkg/gtk/v4"
	"os"
	"runtime"
)

// Only the explicitly selected ISO packaging target sets this to "true".
var defaultLive = "false"

func main() {
	runtime.LockOSThread()
	app := gtk.NewApplication("org.kiki.Installer", gio.ApplicationNonUnique)
	app.ConnectActivate(func() { buildUI(app) })
	os.Exit(app.Run([]string{os.Args[0]}))
}
