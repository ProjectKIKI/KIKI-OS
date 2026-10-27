//go:build linux

package main

import (
	"bytes"
	"fmt"
	"os"
	"syscall"
	"testing"
	"time"
	"unsafe"
)

func ptyIoctl(fd uintptr, request uintptr, value *int32) error {
	_, _, errno := syscall.Syscall(syscall.SYS_IOCTL, fd, request, uintptr(unsafe.Pointer(value)))
	if errno != 0 {
		return errno
	}
	return nil
}

func TestKoreanInputOnPseudoTerminal(t *testing.T) {
	master, err := os.OpenFile("/dev/ptmx", os.O_RDWR, 0)
	if err != nil {
		t.Skipf("PTY unavailable: %v", err)
	}
	defer master.Close()
	var unlock int32
	if err = ptyIoctl(master.Fd(), syscall.TIOCSPTLCK, &unlock); err != nil {
		t.Fatal(err)
	}
	var number int32
	if err = ptyIoctl(master.Fd(), syscall.TIOCGPTN, &number); err != nil {
		t.Fatal(err)
	}
	slave, err := os.OpenFile(fmt.Sprintf("/dev/pts/%d", number), os.O_RDWR, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer slave.Close()
	var display bytes.Buffer
	reader := &hangulLineReader{in: slave, out: &display, prompt: "kiki-ai> "}
	result := make(chan string, 1)
	go func() {
		line := make([]byte, 256)
		n, e := reader.Read(line)
		if e != nil {
			result <- e.Error()
		} else {
			result <- string(line[:n])
		}
	}()
	time.Sleep(30 * time.Millisecond)
	if _, err = master.Write([]byte{0, 'd', 'k', 's', 's', 'u', 'd', '\r'}); err != nil {
		t.Fatal(err)
	}
	select {
	case got := <-result:
		if got != "안녕\n" {
			t.Fatalf("got %q", got)
		}
		if !bytes.Contains(display.Bytes(), []byte("안녕")) {
			t.Fatal("Korean text was not rendered")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("terminal input timed out")
	}
}
