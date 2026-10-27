//go:build !linux

package main

import "io"

type hangulLineReader struct{ prompt string }

func maybeHangulInput(in io.Reader, _ io.Writer) (io.Reader, *hangulLineReader) {
	return in, nil
}
