"""Serial capture and command queue for only the freshly created PNG lab VM."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import time

root = Path(r'E:\dev\KIKI-OS\artifacts\gnome50-session-vm-20261017')
state = json.loads((root / 'vm.json').read_text(encoding='utf-8-sig'))
if state['name'] != 'kiki-gnome50-session-20261017' or state['scope'] != 'fresh-disposable-gnome50-session':
    raise ValueError('not the new PNG lab VM')
pipe_name = r'\\.\pipe\kiki-gnome50-session-20261017-com1'
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                              wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel.CreateFileW.restype = wintypes.HANDLE
kernel.PeekNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
kernel.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                           ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
kernel.WriteFile.argtypes = kernel.ReadFile.argtypes
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
handle = None
for _ in range(1200):
    candidate = kernel.CreateFileW(pipe_name, 0xC0000000, 0, None, 3, 0, None)
    if candidate != wintypes.HANDLE(-1).value:
        handle = candidate
        break
    time.sleep(.1)
if handle is None:
    raise TimeoutError('new VM serial pipe unavailable')
input_file = root / 'serial-input.txt'
offset = input_file.stat().st_size if input_file.exists() else 0
print('Connected to new VM serial pipe', flush=True)
try:
    with (root / 'serial.log').open('ab', buffering=0) as log:
        while not (root / 'serial-stop').exists():
            available = wintypes.DWORD()
            if not kernel.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
                error = ctypes.get_last_error()
                if error in (109, 233):
                    print('\nVM serial disconnected.', flush=True)
                    break
                raise ctypes.WinError(error)
            if available.value:
                buffer = ctypes.create_string_buffer(min(available.value, 65536))
                got = wintypes.DWORD()
                if not kernel.ReadFile(handle, buffer, len(buffer), ctypes.byref(got), None):
                    raise ctypes.WinError(ctypes.get_last_error())
                data = buffer.raw[:got.value]
                log.write(data)
                print(data.decode('utf-8', errors='replace'), end='', flush=True)
            if input_file.exists():
                pending = input_file.read_bytes()
                if len(pending) > offset:
                    payload = pending[offset:]
                    sent = wintypes.DWORD()
                    if not kernel.WriteFile(handle, payload, len(payload), ctypes.byref(sent), None):
                        raise ctypes.WinError(ctypes.get_last_error())
                    offset += sent.value
            time.sleep(.05)
finally:
    kernel.CloseHandle(handle)
