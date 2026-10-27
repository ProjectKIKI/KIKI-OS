//go:build gtk

package main

import (
	"context"
	"flag"
	"fmt"
	"github.com/diamondburned/gotk4/pkg/glib/v2"
	"github.com/diamondburned/gotk4/pkg/gtk/v4"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type installerUI struct {
	app                            *gtk.Application
	window                         *gtk.ApplicationWindow
	stack                          *gtk.Stack
	entries                        map[string]*gtk.Entry
	choices                        map[string]*gtk.DropDown
	options                        map[string][]string
	password, confirm              *gtk.Entry
	erase                          *gtk.CheckButton
	status, review, progressText   *gtk.Label
	progress                       *gtk.ProgressBar
	back, next, install, reboot    *gtk.Button
	page                           int
	live, busy, running, completed bool
	reviewed                       Config
	plan                           []byte
	planPath, workDir, binary      string
	lastProgress                   string
	changed                        time.Time
	korean                         bool
}

func (u *installerUI) t(english, korean string) string {
	if u.korean {
		return korean
	}
	return english
}

func label(s string) *gtk.Label {
	l := gtk.NewLabel(s)
	l.SetXAlign(0)
	l.SetWrap(true)
	return l
}
func (u *installerUI) field(box *gtk.Box, key, title, value string) *gtk.Entry {
	box.Append(label(title))
	e := gtk.NewEntry()
	e.SetText(value)
	e.SetHExpand(true)
	box.Append(e)
	u.entries[key] = e
	return e
}
func (u *installerUI) choice(box *gtk.Box, key, title string, items []string) {
	box.Append(label(title))
	d := gtk.NewDropDownFromStrings(items)
	box.Append(d)
	u.choices[key] = d
	u.options[key] = items
}
func (u *installerUI) config() Config {
	c := defaults()
	for key, e := range u.entries {
		c.Values[key] = e.Text()
	}
	delete(c.Values, "password")
	delete(c.Values, "confirmation")
	for key, d := range u.choices {
		i := int(d.Selected())
		if i < len(u.options[key]) {
			c.Values[key] = u.options[key][i]
		} else {
			c.Values[key] = ""
		}
	}
	if c.Values["xorg"] == "Install Xorg runtime" {
		c.Values["groups"] = addPackageGroup(c.Values["groups"], "xorg-runtime")
	}
	delete(c.Values, "xorg")
	// Placeholders are UI-only and must never reach the backend.
	if strings.HasPrefix(c.Values["disk"], "Select ") {
		c.Values["disk"] = ""
	}
	if strings.HasPrefix(c.Values["network_interface"], "No ") {
		c.Values["network_interface"] = ""
	}
	if c.Values["network"] != "static" {
		c.Values["address"] = ""
		c.Values["gateway"] = ""
	}
	if c.Values["network"] == "off" {
		c.Values["network_interface"] = ""
		c.Values["dns"] = ""
	}
	c.Password = u.password.Text()
	c.Confirmation = u.confirm.Text()
	c.Erase = u.erase.Active()
	return c
}

var pageNames = []string{"disk", "network", "account", "review", "progress"}

func (u *installerUI) show(index int) {
	u.page = index
	u.stack.SetVisibleChildName(pageNames[index])
	u.back.SetSensitive(index > 0 && index < 4 && !u.busy)
	u.next.SetVisible(index < 3)
	u.next.SetSensitive(!u.busy)
	u.install.SetVisible(index == 3)
	u.erase.SetVisible(index == 3)
	u.install.SetSensitive(u.live && !u.busy && u.erase.Active())
}
func buildUI(app *gtk.Application) {
	live := flag.Bool("live", defaultLive == "true", "enable install requests inside the KIKI installer environment")
	smoke := flag.Bool("smoke", false, "open the preview briefly and exit without installing")
	flag.Parse()
	if *live && *smoke {
		fmt.Fprintln(os.Stderr, "--smoke cannot be combined with --live")
		app.Quit()
		return
	}
	chooser := gtk.NewApplicationWindow(app)
	chooser.SetTitle("Scratch Pad — Language / 언어")
	chooser.SetDefaultSize(540, 280)
	box := gtk.NewBox(gtk.OrientationVertical, 16)
	box.SetMarginTop(28)
	box.SetMarginBottom(28)
	box.SetMarginStart(28)
	box.SetMarginEnd(28)
	box.Append(label("Installer language / 인스톨러 언어"))
	box.Append(label("The installed OS language is selected separately. / 설치할 OS의 언어는 별도로 선택합니다."))
	english := gtk.NewButtonWithLabel("English")
	korean := gtk.NewButtonWithLabel("한국어")
	english.AddCSSClass("suggested-action")
	english.ConnectClicked(func() { buildMainUI(app, *live, *smoke, false); chooser.Close() })
	korean.ConnectClicked(func() { buildMainUI(app, *live, *smoke, true); chooser.Close() })
	box.Append(english)
	box.Append(korean)
	chooser.SetChild(box)
	chooser.Present()
	if *smoke {
		glib.TimeoutAdd(1500, func() bool { fmt.Println("GOTK_UI_SMOKE_OK"); app.Quit(); return false })
	}
}

func buildMainUI(app *gtk.Application, live, smoke, korean bool) {
	u := &installerUI{app: app, live: live, korean: korean, entries: map[string]*gtk.Entry{}, choices: map[string]*gtk.DropDown{}, options: map[string][]string{}}
	u.binary = os.Getenv("KIKI_INSTALLER_TUI")
	if u.binary == "" {
		u.binary = "/usr/bin/kiki-installer-tui"
	}
	u.window = gtk.NewApplicationWindow(app)
	u.window.SetTitle("KIKI OS Scratch Pad")
	u.window.SetDefaultSize(960, 720)
	u.window.ConnectCloseRequest(func() bool { return u.running || u.busy })
	root := gtk.NewBox(gtk.OrientationVertical, 16)
	root.SetMarginTop(24)
	root.SetMarginBottom(24)
	root.SetMarginStart(32)
	root.SetMarginEnd(32)
	header := label("KIKI · 키키 Scratch Pad")
	header.AddCSSClass("title-1")
	root.Append(header)
	mode := u.t("PREVIEW — installation is disabled", "미리보기 — 설치 기능이 비활성화되어 있습니다")
	if u.live {
		mode = u.t("Installation — selected disk data will be erased", "설치 — 선택한 디스크의 데이터가 삭제됩니다")
	}
	root.Append(label(mode))
	u.stack = gtk.NewStack()
	u.stack.SetVExpand(true)
	root.Append(u.stack)
	pages := map[string]*gtk.Box{}
	for _, name := range pageNames {
		box := gtk.NewBox(gtk.OrientationVertical, 10)
		scroll := gtk.NewScrolledWindow()
		scroll.SetChild(box)
		scroll.SetVExpand(true)
		u.stack.AddNamed(scroll, name)
		pages[name] = box
	}
	disk := pages["disk"]
	disk.Append(label(u.t("1. Select the installation disk", "1. 설치 디스크 선택")))
	u.choice(disk, "disk", u.t("Whole disk (all existing data will be erased)", "전체 디스크 (기존 데이터 삭제)"), append([]string{"Select a disk…"}, disks()...))
	disk.Append(label(u.t("Never select the installer media. The backend also validates the target before formatting.", "인스톨러 미디어를 선택하지 마세요. 포맷 전 백엔드에서도 대상 디스크를 검사합니다.")))
	u.choice(disk, "swap", u.t("Swap policy", "스왑 정책"), []string{"auto", "off", "on"})
	network := pages["network"]
	network.Append(label(u.t("2. Network", "2. 네트워크")))
	devices := nics()
	if len(devices) == 0 {
		devices = []string{"No hardware NIC detected"}
	}
	u.choice(network, "network_interface", u.t("Management interface", "관리 네트워크 장치"), devices)
	u.choice(network, "network", u.t("Address mode", "주소 방식"), []string{"dhcp", "static", "off"})
	if len(devices) == 1 && strings.HasPrefix(devices[0], "No ") {
		u.choices["network"].SetSelected(2)
	}
	u.field(network, "address", u.t("Static IP / prefix (static mode only)", "고정 IP / 프리픽스 (고정 모드)"), "")
	u.field(network, "gateway", u.t("Gateway (static mode only)", "게이트웨이 (고정 모드)"), "")
	u.field(network, "dns", u.t("DNS servers (optional; comma separated)", "DNS 서버 (선택, 쉼표로 구분)"), "")
	account := pages["account"]
	account.Append(label(u.t("3. Account and installation options", "3. 계정 및 설치 옵션")))
	c := defaults()
	if !u.korean {
		c.Values["locale"], c.Values["keymap"], c.Values["timezone"] = "en_US.UTF-8", "us", "UTC"
	}
	u.field(account, "hostname", u.t("Hostname", "호스트명"), c.Values["hostname"])
	u.field(account, "user", u.t("Administrator", "관리자"), c.Values["user"])
	u.password = u.field(account, "password", u.t("Password (8–95 UTF-8 bytes)", "암호 (UTF-8 8~95바이트)"), "")
	u.password.SetVisibility(false)
	u.confirm = u.field(account, "confirmation", u.t("Confirm password", "암호 확인"), "")
	u.confirm.SetVisibility(false)
	advanced := gtk.NewExpander(u.t("Advanced: profile, language and AI", "고급: 프로필, 시스템 언어 및 AI"))
	options := gtk.NewBox(gtk.OrientationVertical, 8)
	advanced.SetChild(options)
	account.Append(advanced)
	u.choice(options, "profile", u.t("Profile", "프로필"), []string{"server-core", "minimal-systemd", "kiki-kube-bootstrap", "kiki-kube-bootstrap-containerd", "kiki-kube-control", "kiki-kube-control-containerd", "kiki-kube-compute", "kiki-kube-compute-containerd"})
	u.choice(options, "xorg", u.t("Xorg runtime (optional; no LightDM or desktop)", "Xorg 런타임 (선택, 데스크톱 제외)"), []string{"Do not install", "Install Xorg runtime"})
	u.choice(options, "runtime", u.t("Container runtime", "컨테이너 런타임"), []string{"profile-default", "none", "crio", "containerd"})
	u.choice(options, "ai", u.t("AI mode", "AI 모드"), []string{"local", "remote", "off"})
	for _, f := range []struct{ key, en, ko string }{{"ai_endpoint", "AI endpoint", "AI 엔드포인트"}, {"groups", "Additional package groups", "추가 패키지 그룹"}, {"locale", "Installed OS locale", "설치할 OS 로케일"}, {"keymap", "Keyboard", "키보드"}, {"timezone", "Time zone", "시간대"}} {
		u.field(options, f.key, u.t(f.en, f.ko), c.Values[f.key])
	}
	u.review = label("")
	u.review.SetSelectable(true)
	pages["review"].Append(u.review)
	u.erase = gtk.NewCheckButtonWithLabel(u.t("I understand: all data on the reviewed disk will be erased", "확인: 선택한 디스크의 모든 데이터가 삭제됩니다"))
	root.Append(u.erase)
	u.erase.ConnectToggled(func() { u.install.SetSensitive(u.live && u.erase.Active() && !u.busy) })
	u.progress = gtk.NewProgressBar()
	u.progress.SetShowText(true)
	pages["progress"].Append(u.progress)
	u.progressText = label(u.t("Waiting for backend", "설치 백엔드 대기 중"))
	pages["progress"].Append(u.progressText)
	pages["progress"].Append(label(u.t("Recovery console: Ctrl+Alt+F2\nBackend log: /run/kiki/gui-install-backend.log\nDo not power off during installation.", "복구 콘솔: Ctrl+Alt+F2\n백엔드 로그: /run/kiki/gui-install-backend.log\n설치 중 전원을 끄지 마세요.")))
	u.reboot = gtk.NewButtonWithLabel(u.t("Reboot after successful installation", "설치 성공 후 재부팅"))
	u.reboot.SetSensitive(false)
	u.reboot.ConnectClicked(func() {
		if !u.completed {
			return
		}
		if err := publish("/run/kiki/gui-reboot.request", []byte("confirm=yes\n")); err != nil {
			u.status.SetText(err.Error())
			return
		}
		u.reboot.SetSensitive(false)
		u.running = true
		u.status.SetText(u.t("Reboot requested", "재부팅을 요청했습니다"))
	})
	pages["progress"].Append(u.reboot)
	u.status = label("")
	root.Append(u.status)
	nav := gtk.NewBox(gtk.OrientationHorizontal, 12)
	u.back = gtk.NewButtonWithLabel(u.t("Back", "이전"))
	u.next = gtk.NewButtonWithLabel(u.t("Next", "다음"))
	u.install = gtk.NewButtonWithLabel(u.t("Erase disk and install", "디스크 삭제 후 설치"))
	u.install.AddCSSClass("destructive-action")
	nav.Append(u.back)
	nav.Append(u.next)
	nav.Append(u.install)
	root.Append(nav)
	u.back.ConnectClicked(func() { u.erase.SetActive(false); u.show(u.page - 1) })
	u.next.ConnectClicked(func() {
		u.status.SetText("")
		if u.page == 2 {
			u.prepareReview()
			return
		}
		if u.page == 0 && u.config().Values["disk"] == "" {
			u.status.SetText(u.t("Select the target disk first.", "먼저 대상 디스크를 선택하세요."))
			return
		}
		u.show(u.page + 1)
	})
	u.install.ConnectClicked(u.start)
	u.window.SetChild(root)
	u.show(0)
	u.window.Present()
	_ = smoke
}
func (u *installerUI) prepareReview() {
	c := u.config()
	// Password validation happens here; erase consent comes only after review.
	c.Erase = true
	if err := c.validate(u.live); err != nil {
		u.status.SetText(err.Error())
		return
	}
	dir, err := os.MkdirTemp("", "kiki-gotk-plan-")
	if err != nil {
		u.status.SetText(err.Error())
		return
	}
	if u.workDir != "" {
		os.Remove(filepath.Join(u.workDir, "install-plan.yaml"))
		os.Remove(u.workDir)
	}
	u.workDir = dir
	u.planPath = filepath.Join(dir, "install-plan.yaml")
	u.busy = true
	u.show(u.page)
	u.status.SetText(u.t("Validating with the existing installation planner…", "설치 계획을 검증하는 중…"))
	go func() {
		plan, err := generatePlan(context.Background(), u.binary, u.planPath, c)
		glib.IdleAdd(func() {
			u.busy = false
			if err != nil {
				u.status.SetText(err.Error())
				u.show(u.page)
				return
			}
			u.reviewed = c
			u.plan = plan
			u.review.SetText(fmt.Sprintf(u.t("4. Review before installation\n\nERASE ENTIRE DISK: %s\nNetwork: %s / %s\nIP: %s   Gateway: %s\nDNS: %s\nAdministrator: %s   Host: %s\nProfile: %s / Runtime: %s\nAI: %s\nLocale: %s / %s / %s\n\nPlan validated by the existing Go installer.\nPasswords are not included in the saved plan.", "4. 설치 전 검토\n\n전체 디스크 삭제: %s\n네트워크: %s / %s\nIP: %s   게이트웨이: %s\nDNS: %s\n관리자: %s   호스트: %s\n프로필: %s / 런타임: %s\nAI: %s\n로케일: %s / %s / %s\n\nGo 인스톨러에서 계획을 검증했습니다.\n저장된 계획에 암호는 포함되지 않습니다."),
				c.Values["disk"], c.Values["network_interface"], c.Values["network"], c.Values["address"], c.Values["gateway"], c.Values["dns"], c.Values["user"], c.Values["hostname"], c.Values["profile"], c.Values["runtime"], c.Values["ai"], c.Values["locale"], c.Values["keymap"], c.Values["timezone"]))
			u.erase.SetActive(false)
			u.status.SetText("")
			u.show(3)
		})
	}()
}
func (u *installerUI) start() {
	if !u.live || u.busy || u.running || !u.erase.Active() {
		return
	}
	if os.Geteuid() != 0 {
		u.status.SetText(u.t("Live installation requires root inside the KIKI installer.", "실제 설치에는 KIKI 인스톨러의 root 권한이 필요합니다."))
		return
	}
	cmdline, err := os.ReadFile("/proc/cmdline")
	if err != nil || !installerSession(string(cmdline)) {
		u.status.SetText(u.t("Live installation is only allowed in the KIKI installer boot session.", "실제 설치는 KIKI 인스톨러 부팅 세션에서만 가능합니다."))
		return
	}
	// Stage-1 discovers, mounts and verifies the media after receiving our request.
	c := u.reviewed
	c.Erase = u.erase.Active()
	if _, err := os.Lstat("/run/kiki/gui-install.request"); !os.IsNotExist(err) {
		u.status.SetText(u.t("An install request already exists, or its status cannot be checked.", "설치 요청이 이미 있거나 상태를 확인할 수 없습니다."))
		return
	}
	if old, err := os.ReadFile("/run/kiki/install-progress.state"); err == nil {
		p, parseErr := parseProgress(old)
		if parseErr != nil || p.State == "running" || p.State == "rebooting" {
			u.status.SetText(u.t("A previous installation may still be running. Check the recovery console.", "이전 설치가 진행 중일 수 있습니다. 복구 콘솔을 확인하세요."))
			return
		}
	} else if !os.IsNotExist(err) {
		u.status.SetText(err.Error())
		return
	}
	data, err := c.request(u.planPath, u.plan)
	if err == nil {
		// Do not allow stale completion from an earlier attempt.
		err = os.Remove("/run/kiki/install-progress.state")
		if os.IsNotExist(err) {
			err = nil
		}
	}
	if err == nil {
		err = publish("/run/kiki/gui-install.request", data)
	}
	if err != nil {
		u.status.SetText(err.Error())
		return
	}
	clear(data)
	u.reviewed.Password = ""
	u.reviewed.Confirmation = ""
	u.password.SetText("")
	u.confirm.SetText("")
	u.running = true
	u.changed = time.Now()
	u.show(4)
	u.status.SetText(u.t("Installation requested. Waiting for backend.", "설치를 요청했습니다. 백엔드를 기다리는 중입니다."))
	glib.TimeoutAdd(500, u.poll)
}
func (u *installerUI) poll() bool {
	data, err := os.ReadFile("/run/kiki/install-progress.state")
	if err == nil {
		p, parseErr := parseProgress(data)
		if parseErr != nil {
			u.status.SetText(parseErr.Error())
			return true
		}
		if string(data) != u.lastProgress {
			u.lastProgress = string(data)
			u.changed = time.Now()
		}
		u.progress.SetFraction(float64(p.Percent) / 100)
		u.progress.SetText(fmt.Sprintf(u.t("%d%% — packages %d / %d", "%d%% — 패키지 %d / %d"), p.Percent, p.Installed, p.Total))
		u.progressText.SetText(p.Phase + "\n" + p.Message)
		if p.State == "failed" || p.State == "completed" {
			u.running = false
			u.completed = p.State == "completed"
			u.reboot.SetSensitive(u.completed)
			u.status.SetText(u.t("Installation "+p.State+". See recovery instructions above.", "설치 상태: "+p.State+". 위의 복구 안내를 확인하세요."))
			return false
		}
	}
	if time.Since(u.changed) > 2*time.Minute {
		u.status.SetText(u.t("No progress update for 2 minutes. Check the recovery console; do not reboot.", "2분간 진행 상태가 바뀌지 않았습니다. 재부팅하지 말고 복구 콘솔을 확인하세요."))
	}
	return true
}
