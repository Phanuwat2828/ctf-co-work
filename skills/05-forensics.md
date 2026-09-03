---
name: Forensics
categories: [forensic, forensics]
tags: [forensic, forensics, memory, pcap, disk]
---

- Run `file` on every artifact first to pick the right toolchain — don't assume the extension
  is correct (challenge files are often mislabeled or extensionless).
- **Disk/filesystem images**: `mmls disk.img` to find partition offsets, then `fls -r -o OFFSET
  disk.img` to list files including deleted ones, `icat -o OFFSET disk.img INODE > out` to
  extract by inode, or `tsk_recover disk.img outdir/` to recover everything at once.
- **Deleted files in archives/raw data**: `binwalk -e file` to carve embedded files by magic
  bytes, or `foremost -i file -o outdir/` as a second pass if binwalk misses something.
- **Memory dumps**: `vol -f dump.raw windows.info` (or `linux.info`) to identify the profile,
  then `windows.pslist`/`windows.cmdline`/`windows.filescan` to find suspicious processes and
  files; `windows.dumpfiles` to extract them.
- **Network captures**: `tshark -r out.pcap` for a summary, then filter and use
  `-q -z follow,tcp,ascii,STREAM` to reconstruct a specific TCP stream's data.
- **Metadata**: `exiftool file` on any image/document — flags are frequently hidden in EXIF
  comment/author fields rather than the visual content.
- Recovered files should be written to `/challenge/workspace/` and then inspected the same way
  as any other distfile (strings, file, binwalk again if nested).
