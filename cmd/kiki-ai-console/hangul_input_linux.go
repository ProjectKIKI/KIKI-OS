//go:build linux

package main

import (
	"io"
	"os"
	"syscall"
	"unsafe"
)

type hangulLineReader struct {
	in     *os.File
	out    io.Writer
	prompt string
	queued []byte
}

func ioctlTermios(fd uintptr, request uintptr, term *syscall.Termios) error {
	_, _, errno := syscall.Syscall(syscall.SYS_IOCTL, fd, request, uintptr(unsafe.Pointer(term)))
	if errno != 0 {
		return errno
	}
	return nil
}

func maybeHangulInput(in io.Reader, out io.Writer) (io.Reader, *hangulLineReader) {
	file, ok := in.(*os.File)
	if !ok || os.Getenv("KIKI_HANGUL_INPUT") != "1" {
		return in, nil
	}
	var term syscall.Termios
	if ioctlTermios(file.Fd(), syscall.TCGETS, &term) != nil {
		return in, nil
	}
	reader := &hangulLineReader{in: file, out: out}
	return reader, reader
}

func (r *hangulLineReader) Read(buffer []byte) (int, error) {
	if len(r.queued) == 0 {
		line, err := r.readLine()
		if err != nil {
			return 0, err
		}
		r.queued = append([]byte(line), '\n')
	}
	n := copy(buffer, r.queued)
	r.queued = r.queued[n:]
	return n, nil
}

func (r *hangulLineReader) readLine() (string, error) {
	var original syscall.Termios
	if err := ioctlTermios(r.in.Fd(), syscall.TCGETS, &original); err != nil {
		return "", err
	}
	raw := original
	raw.Lflag &^= syscall.ICANON | syscall.ECHO
	raw.Cc[syscall.VMIN] = 1
	raw.Cc[syscall.VTIME] = 0
	if err := ioctlTermios(r.in.Fd(), syscall.TCSETS, &raw); err != nil {
		return "", err
	}
	defer ioctlTermios(r.in.Fd(), syscall.TCSETS, &original)
	h := hangulComposer{l: -1, v: -1}
	korean := false
	var one [1]byte
	redraw := func() { _, _ = io.WriteString(r.out, "\r\x1b[2K"+r.prompt+h.text()) }
	for {
		if _, err := r.in.Read(one[:]); err != nil {
			return "", err
		}
		key := one[0]
		switch key {
		case 0: // Ctrl+Space: switch between English and two-set Korean.
			h.flush()
			korean = !korean
		case '\r', '\n':
			h.flush()
			_, _ = io.WriteString(r.out, "\r\n")
			return h.text(), nil
		case 127, 8:
			h.backspace()
		case 4: // Ctrl+D on an empty line.
			if h.text() == "" {
				return "", io.EOF
			}
		default:
			if key >= 32 && key < 127 {
				if korean {
					h.feed(key)
				} else {
					h.flush()
					h.committed.WriteByte(key)
				}
			}
		}
		redraw()
	}
}
