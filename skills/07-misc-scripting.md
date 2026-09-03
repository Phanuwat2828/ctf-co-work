---
name: Misc / Scripting Puzzles
categories: [misc, scripting]
tags: [misc, scripting, osint, esolang]
---

- Layered encodings are common: decode base64/hex/rot13/url-encoding repeatedly in a loop until
  the output stops changing or stabilizes into readable text — write a script to automate this
  rather than decoding by hand one layer at a time.
- Custom network protocols: write a Python `socket`/pwntools script to interact statefully
  instead of relying on manual `nc` heredocs — much easier to iterate on.
- Esolangs/custom VMs: if an interpreter/spec is provided, read it carefully for the opcode
  format before trying to reverse-engineer behavior from execution alone.
- Re-read the challenge description and name for wordplay or format hints before resorting to
  brute-force — misc challenges often encode the technique in the title.
- OSINT-style challenges: check attached files' metadata, and search distinctive strings from
  the challenge (usernames, filenames, unique phrases) as-is before assuming they're encoded.
