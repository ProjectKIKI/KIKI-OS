package main

import "strings"

// hangulComposer implements the common two-set Korean keyboard layout.
// It keeps the unfinished syllable separate so a following vowel can move
// its final consonant to the next syllable.
type hangulComposer struct {
	committed strings.Builder
	l, v, t   int
}

var choseong = []rune("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")
var jungseong = []rune("ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ")
var jongseong = []rune(" ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ")

func indexRune(rs []rune, r rune) int {
	for i, value := range rs {
		if value == r {
			return i
		}
	}
	return -1
}

func keyboardJamo(key byte) rune {
	if key >= 'A' && key <= 'Z' && key != 'R' && key != 'E' && key != 'Q' && key != 'T' && key != 'W' && key != 'O' && key != 'P' {
		key += 'a' - 'A'
	}
	switch key {
	case 'r':
		return 'ㄱ'
	case 'R':
		return 'ㄲ'
	case 's':
		return 'ㄴ'
	case 'e':
		return 'ㄷ'
	case 'E':
		return 'ㄸ'
	case 'f':
		return 'ㄹ'
	case 'a':
		return 'ㅁ'
	case 'q':
		return 'ㅂ'
	case 'Q':
		return 'ㅃ'
	case 't':
		return 'ㅅ'
	case 'T':
		return 'ㅆ'
	case 'd':
		return 'ㅇ'
	case 'w':
		return 'ㅈ'
	case 'W':
		return 'ㅉ'
	case 'c':
		return 'ㅊ'
	case 'z':
		return 'ㅋ'
	case 'x':
		return 'ㅌ'
	case 'v':
		return 'ㅍ'
	case 'g':
		return 'ㅎ'
	case 'k':
		return 'ㅏ'
	case 'o':
		return 'ㅐ'
	case 'i':
		return 'ㅑ'
	case 'O':
		return 'ㅒ'
	case 'j':
		return 'ㅓ'
	case 'p':
		return 'ㅔ'
	case 'u':
		return 'ㅕ'
	case 'P':
		return 'ㅖ'
	case 'h':
		return 'ㅗ'
	case 'y':
		return 'ㅛ'
	case 'n':
		return 'ㅜ'
	case 'b':
		return 'ㅠ'
	case 'm':
		return 'ㅡ'
	case 'l':
		return 'ㅣ'
	}
	return 0
}

func combineVowel(a, b int) int {
	pairs := map[[2]int]int{{8, 0}: 9, {8, 1}: 10, {8, 20}: 11, {13, 4}: 14, {13, 5}: 15, {13, 20}: 16, {18, 20}: 19}
	if combined, ok := pairs[[2]int{a, b}]; ok {
		return combined
	}
	return -1
}

func combineFinal(a, b int) int {
	pairs := map[[2]int]int{{1, 19}: 3, {4, 22}: 5, {4, 27}: 6, {8, 1}: 9, {8, 16}: 10, {8, 17}: 11, {8, 19}: 12, {8, 25}: 13, {8, 26}: 14, {8, 27}: 15, {17, 19}: 18}
	if combined, ok := pairs[[2]int{a, b}]; ok {
		return combined
	}
	return -1
}

func splitFinal(t int) (int, rune) {
	split := map[int]struct {
		first  int
		second rune
	}{
		3: {1, 'ㅅ'}, 5: {4, 'ㅈ'}, 6: {4, 'ㅎ'}, 9: {8, 'ㄱ'}, 10: {8, 'ㅁ'},
		11: {8, 'ㅂ'}, 12: {8, 'ㅅ'}, 13: {8, 'ㅌ'}, 14: {8, 'ㅍ'}, 15: {8, 'ㅎ'}, 18: {17, 'ㅅ'},
	}
	if pair, ok := split[t]; ok {
		return pair.first, pair.second
	}
	return 0, jongseong[t]
}

func (h *hangulComposer) pending() string {
	if h.l < 0 {
		return ""
	}
	if h.v < 0 {
		return string(choseong[h.l])
	}
	return string(rune(0xAC00 + (h.l*21+h.v)*28 + h.t))
}

func (h *hangulComposer) flush() {
	h.committed.WriteString(h.pending())
	h.l, h.v, h.t = -1, -1, 0
}

func (h *hangulComposer) text() string { return h.committed.String() + h.pending() }

func (h *hangulComposer) feed(key byte) {
	r := keyboardJamo(key)
	if r == 0 {
		h.flush()
		h.committed.WriteByte(key)
		return
	}
	l := indexRune(choseong, r)
	v := indexRune(jungseong, r)
	if h.l < 0 {
		if l >= 0 {
			h.l = l
		} else {
			h.committed.WriteRune(r)
		}
		return
	}
	if h.v < 0 {
		if v >= 0 {
			h.v = v
		} else {
			h.flush()
			h.l = l
		}
		return
	}
	if v >= 0 {
		if h.t == 0 {
			if combined := combineVowel(h.v, v); combined >= 0 {
				h.v = combined
				return
			}
		} else {
			first, second := splitFinal(h.t)
			h.t = first
			h.flush()
			h.l, h.v = indexRune(choseong, second), v
			return
		}
		h.flush()
		h.committed.WriteRune(r)
		return
	}
	t := indexRune(jongseong, r)
	if h.t == 0 && t > 0 {
		h.t = t
		return
	}
	if h.t > 0 && t > 0 {
		if combined := combineFinal(h.t, t); combined > 0 {
			h.t = combined
			return
		}
	}
	h.flush()
	h.l = l
}

func (h *hangulComposer) backspace() {
	if h.l >= 0 {
		if h.t > 0 {
			h.t = 0
		} else if h.v >= 0 {
			h.v = -1
		} else {
			h.l = -1
		}
		return
	}
	runes := []rune(h.committed.String())
	if len(runes) > 0 {
		h.committed.Reset()
		h.committed.WriteString(string(runes[:len(runes)-1]))
	}
}
