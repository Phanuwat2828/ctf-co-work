---
name: Steganography
categories: [stego, steganography]
tags: [stego, steganography, lsb]
---

- Always run `exiftool file` and `strings file` before anything else — many stego challenges
  hide the flag in plain metadata or an appended text blob, no extraction tool needed.
- `binwalk file` to check for a second file appended/embedded (zip, another image, etc.);
  `binwalk -e file` to carve it out.
- For JPEG/BMP: try `steghide extract -sf file.jpg` (empty passphrase first), then
  `stegseek file.jpg /usr/share/wordlists/rockyou.txt` to brute-force a passphrase.
- For PNG/BMP: `zsteg file.png` automatically tries LSB extraction across channels/bit-planes —
  run this before manually writing LSB-extraction code.
- For audio (WAV/MP3): `sox in.wav -n spectrogram -o spec.png` and inspect the spectrogram
  visually — text/QR codes are commonly hidden in the frequency domain.
- For QR codes hidden or corrupted in images: crop/threshold with ImageMagick (`convert`) to
  isolate and clean the code before decoding.
- If the image file itself looks corrupted (wrong dimensions, viewer errors), check magic bytes
  and header fields with `xxd`/`pngcheck` — the challenge may want you to repair it first.
