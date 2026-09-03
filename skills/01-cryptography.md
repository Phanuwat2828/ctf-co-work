---
name: Cryptography
categories: [crypto]
tags: [crypto, rsa, aes, xor, cipher, hash, jwt]
---

- Identify the primitive first: RSA (n/e/c present), AES (16-byte-aligned ciphertext), XOR,
  classical cipher (Caesar/Vigenere), hash, or JWT. Don't guess an attack before you know the primitive.
- **RSA**: try `RsaCtfTool -n N -e E --attack all` first — it automates common-factor,
  Wiener, Fermat, small-e, and known-attack detection. If multiple (n, c) pairs exist across
  files/challenges, check for a shared prime via `gcd`. For small e (e.g. e=3) with no padding,
  try Hastad's broadcast attack given enough ciphertexts. Fermat factorization if p and q are close.
- **AES**: ECB mode leaks patterns — look for repeated 16-byte ciphertext blocks. CBC without
  MAC is vulnerable to bit-flipping and padding-oracle attacks. Reused nonce/IV in CTR/GCM
  lets you XOR two ciphertexts to cancel the keystream.
- **XOR**: single-byte key — brute-force all 256 values and score by printable-ASCII ratio.
  Repeating-key — estimate key length via Hamming distance between blocks, then solve each
  key-byte position independently (frequency analysis).
- **Classical ciphers**: try all 26 Caesar shifts programmatically; check for base64/hex layered
  on top (decode repeatedly until output stabilizes or stops changing).
- **Hash/JWT**: for cracking use `john`/`hashcat` with rockyou. For JWT, test `alg: none`,
  RS256-to-HS256 key confusion (sign with the public key as an HMAC secret), and weak/guessable secrets.
- Always verify decoded output looks like a real flag before calling `submit_flag`.
