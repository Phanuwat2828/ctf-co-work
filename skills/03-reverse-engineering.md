---
name: Reverse Engineering
categories: [rev, reversing]
tags: [rev, reversing, re]
---

- Start static: `file binary`, `checksec --file=binary`, `strings -n 8 binary` before touching
  a debugger — often the flag or key logic is visible immediately.
- Decompile with `pyghidra` (Python API) or `radare2` (`r2 -A binary`, `pdf @main`, `afl` to list
  functions). Prefer decompiled pseudocode over raw disassembly for speed.
- If the binary is UPX-packed (`file` shows small size / weird section names), unpack first:
  `upx -d binary`, then re-run static analysis on the unpacked copy.
- Dynamic analysis: `gdb` for breakpoints/memory inspection, `ltrace`/`strace` to see library
  and syscall behavior without reading disassembly.
- Python bytecode (`.pyc`): use `uncompyle6`/`decompyle3`/`pycdc` if available, or read
  bytecode with the `dis` module manually if decompilers fail on the Python version.
- If checks look intentionally slow to reverse by hand (character-by-character comparison,
  complex arithmetic on input), consider symbolic execution with `angr` or constraint solving
  with `z3` instead of manually reasoning through the logic.
- Patch anti-debug checks (`ptrace` calls, timing checks) with a hex editor or by NOPing them
  out if dynamic analysis is blocked.
