#!/usr/bin/env python3
"""Probe the native target crypto and GTK/GIO libraries without host-library fallback."""
import json
import subprocess
import ki2sessioncandidate as c

out=c.WORK/'runtime-smoke';out.mkdir(exist_ok=True)
source=out/'nss-probe.c'
source.write_text('''#include <nss.h>
#include <pk11pub.h>
#include <prerror.h>
#include <stdio.h>
int main(void) {
 unsigned char sample[16];
 if (NSS_NoDB_Init(NULL) != SECSuccess) { printf("NSS_INIT_ERROR %d\\n", PR_GetError()); return 1; }
 if (PK11_GenerateRandom(sample, sizeof sample) != SECSuccess) { printf("NSS_RANDOM_ERROR %d\\n", PR_GetError()); return 2; }
 if (NSS_Shutdown() != SECSuccess) return 3;
 puts("NSS_TARGET_INIT_RANDOM_OK"); return 0;
}
''')
log=c.TARGET/'validation/desktop-library-runtime.log'
flags=subprocess.check_output(['pkg-config','--cflags','--libs','nss'],env=c.environment(),text=True).split()
c.run(['gcc']+c.environment()['CFLAGS'].split()+[str(source),'-o',str(out/'nss-probe')]+flags+c.environment()['LDFLAGS'].split(),out,log)
run=c.TARGET/'inputs/distro/scripts/ki2-target-run'
env=dict(KI2_USE_TARGET_LOADER='1',KI2_REPO_ROOT=str(c.TARGET/'inputs'),KI2_BUILD_DIR=str(out),
         GIO_MODULE_DIR=str(c.SDK/'usr/lib/gio/modules'),GSETTINGS_SCHEMA_DIR=str(c.SDK/'usr/share/glib-2.0/schemas'),GSETTINGS_BACKEND='memory')
c.run(['/bin/sh',str(run),str(out/'nss-probe')],out,log,env)
c.run(['/bin/sh',str(run),str(c.SDK/'usr/bin/gio-querymodules'),str(c.SDK/'usr/lib/gio/modules')],out,log,env)
c.run([str(c.SDK/'usr/bin/glib-compile-schemas'),str(c.SDK/'usr/share/glib-2.0/schemas')],out,log,env)
gjs=c.SDK/'usr/bin/gjs.kiki-real'
if not gjs.exists():raise ValueError('Expected scoped GJS launcher')
code="imports.gi.versions.Gtk='4.0'; imports.gi.versions.Adw='1'; const {Gio,Gtk,Adw}=imports.gi; if(!Gio.TlsBackend.get_default().supports_tls()) throw new Error('TLS backend absent'); print('GTK_ADW_GIO_TARGET_OK', Gtk.get_major_version(), Gtk.get_minor_version(), Adw.get_major_version(), Adw.get_minor_version());"
c.run(['/bin/sh',str(run),str(gjs),'-c',code],out,log,env)
c.save(c.TARGET/'validation/desktop-library-runtime.json',dict(passed=True,scope='Target-loader smoke on builder; NSS module integrity/random and GTK/Libadwaita/GIO TLS backend; no graphical-login claim',nss_package=json.loads((c.TARGET/'validation/nss-build.json').read_text())['sha256'],probe_source_sha256=c.sha256_file(source)))
print('Native NSS and GTK/Adwaita/GIO library probes passed')
