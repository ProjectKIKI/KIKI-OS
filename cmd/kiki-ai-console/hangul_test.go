package main

import "testing"

func composeKeys(keys string) string {
	h := hangulComposer{l: -1, v: -1}
	for i := 0; i < len(keys); i++ {
		h.feed(keys[i])
	}
	h.flush()
	return h.text()
}

func TestTwoSetKorean(t *testing.T) {
	cases := map[string]string{
		"dkssudgktpdy":  "안녕하세요",
		"gksrmf dlqfur": "한글 입력",
		"rhk":           "과",
		"rkt":           "갓",
		"rkrtk":         "각사",
	}
	for keys, want := range cases {
		if got := composeKeys(keys); got != want {
			t.Errorf("%q: got %q, want %q", keys, got, want)
		}
	}
}

func TestHangulBackspace(t *testing.T) {
	h := hangulComposer{l: -1, v: -1}
	h.feed('r')
	h.feed('k')
	h.feed('s')
	h.backspace()
	if got := h.text(); got != "가" {
		t.Fatalf("got %q", got)
	}
	h.backspace()
	if got := h.text(); got != "ㄱ" {
		t.Fatalf("got %q", got)
	}
	h.backspace()
	if got := h.text(); got != "" {
		t.Fatalf("got %q", got)
	}
}
