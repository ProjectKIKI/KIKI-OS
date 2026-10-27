package aiconsole

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"time"
)

type inventoryCommand struct {
	Name string
	Argv []string
}

func CollectInventory(ctx context.Context) string {
	commands := []inventoryCommand{
		{Name: "Kernel", Argv: []string{"uname", "-a"}},
		{Name: "Network links", Argv: []string{"ip", "-j", "link"}},
		{Name: "Network addresses", Argv: []string{"ip", "-j", "address"}},
		{Name: "Routes", Argv: []string{"ip", "-j", "route"}},
		{Name: "Block devices", Argv: []string{"lsblk", "-J", "-o", "NAME,KNAME,PATH,SIZE,TYPE,FSTYPE,FSVER,LABEL,UUID,MOUNTPOINTS,MODEL,SERIAL,RO,RM"}},
		{Name: "Mounts", Argv: []string{"findmnt", "-J"}},
		{Name: "Failed services", Argv: []string{"systemctl", "--failed", "--no-legend", "--plain"}},
	}
	var output strings.Builder
	for _, item := range commands {
		commandContext, cancel := context.WithTimeout(ctx, 3*time.Second)
		command := exec.CommandContext(commandContext, item.Argv[0], item.Argv[1:]...)
		var stdout, stderr bytes.Buffer
		command.Stdout = &stdout
		command.Stderr = &stderr
		err := command.Run()
		cancel()
		fmt.Fprintf(&output, "[%s]\n", item.Name)
		if err != nil {
			fmt.Fprintf(&output, "Unavailable: %v %s\n", err, truncate(stderr.String(), 1024))
			continue
		}
		text := truncate(stdout.String(), 32<<10)
		output.WriteString(text)
		if !strings.HasSuffix(text, "\n") {
			output.WriteByte('\n')
		}
	}
	if data, err := os.ReadFile("/proc/meminfo"); err == nil {
		output.WriteString("[Memory]\n")
		output.WriteString(truncate(string(data), 4096))
	}
	return truncate(output.String(), 128<<10)
}

func truncate(value string, limit int) string {
	if len(value) <= limit {
		return value
	}
	return value[:limit] + "\n... truncated ...\n"
}
