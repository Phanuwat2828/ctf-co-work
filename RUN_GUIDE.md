# คู่มือการรัน CTF Sandbox (CO WORK)

คู่มือฉบับเต็ม — ตั้งแต่สร้าง Docker image จนถึงใช้งาน web dashboard เพื่อแก้โจทย์ CTF ด้วย swarm ของ AI models หลายตัว

---

## 0. สิ่งที่ต้องมีก่อน

| สิ่งที่ต้องมี | หมายเหตุ |
|---|---|
| **Docker** | ต้องรันได้ (ดูข้อ 0.1) |
| **Python 3.14+** | ใช้รัน host |
| **`uv`** | ตัวจัดการ dependencies (run.sh ติดตั้งให้อัตโนมัติ) |
| **API key อย่างน้อย 1 ตัว** | Claude (ANTHROPIC) / OpenAI / Google หรือ custom provider |
| **CTFd** | แพลตฟอร์มโจทย์ (URL + session cookie หรือ API token) |

### 0.1 ตรวจ Docker ให้เข้าถึงได้

```bash
docker ps
# ถ้า error "permission denied" → เพิ่มตัวเองใน docker group แล้ว login ใหม่
sudo usermod -aG docker $USER
newgrp docker        # เปิด session ใหม่พร้อม docker group (หรือ logout/login)
docker ps            # ต้องขึ้นรายการ container ได้
```

> สำคัญ: ถ้า shell ที่รัน `./run.sh` ยังไม่มี docker group, swarm จะสร้าง container ไม่ได้ (dashboard จะขึ้น banner แดงเตือน)

---

## 1. สร้าง Docker sandbox image

```bash
# จากโฟลเดอร์โปรเจกต์
docker build -f sandbox/Dockerfile.sandbox -t ctf-sandbox .
```

หรือใช้สคริปต์ช่วย (build + ติดตั้ง deps + รัน ครบในตัว):

```bash
./run.sh --build-only     # build image อย่างเดียว
```

**รายละเอียด image** (Kali Linux):
- มี tools CTF ครบ: pwntools, radare2, ghidra, RsaCtfTool, cado-nfs, flatter, volatility3, ฯลฯ
- Python environment ใช้ **Python 3.12** (uv-managed) เพราะ lib CTF บางตัวยังไม่รองรับ 3.14
- `TOOLSET=ctf` (default) — ใช้ `--build-arg TOOLSET=everything` ถ้าอยากได้ทุกอย่าง (ใหญ่ขึ้นมาก)
- ใช้เวลาสร้างค่อนข้างนาน (โดยเฉพาะ CADO-NFS compile) — build ค้างไว้ก่อนก็ได้

---

## 2. ติดตั้ง dependencies (host)

```bash
./run.sh                # จะรัน uv sync ให้อัตโนมัติก่อนเริ่ม
# หรือ manual:
uv sync
```

---

## 3. ตั้งค่า (ผ่านเว็บได้ ไม่ต้องแก้ไฟล์)

เปิด dashboard หลังรันแล้วใช้ปุ่ม **Settings** และ **Providers** — ไม่ต้องแก้ `.env` ด้วยมือ

### 3.1 CTFd (Settings)
- **CTFd URL**: เช่น `http://10.31.7.218`
- **CTFd session cookie**: เอามาจาก browser
  1. ล็อกอิน CTFd ใน browser
  2. F12 → Network → refresh → คลิก request ไหนก็ได้ → Headers
  3. คัดลอกค่าหลัง `Cookie: session=...` มาวาง (ถ้า token มีรูปแบบ `ctfd_...` ก็ใช้ช่อง token ได้แทน)
- กด **Test** ให้เห็น "connected via session cookie — N challenges visible"

### 3.2 Model provider (Providers)
- กด **Providers** → **Add provider**
- กรอก: Name, **API format**, **Base URL**, API key, รายชื่อ models (ทีละบรรทัด)
- **ระวัง**: base URL ต้องมี `/v1` ต่อท้ายถ้า API ของเจ้านั้นใช้ (เช่น `https://.../v1`) — ถ้า Test ขึ้น "non-JSON" ให้เติม `/v1` ดู
- ตัวอย่าง format:
  - `OpenAI Chat Completions (/v1/chat/completions)` — ส่วนใหญ่ใช้ตัวนี้
  - `Anthropic Messages (/v1/messages)` — Claude API / proxy แบบ Anthropic
  - `Claude SDK` / `Codex CLI` — ใช้แบบ subscription

### 3.3 การตั้งค่าแบบ manual (ทางเลือก)
สร้าง `.env` จาก `.env.example` แล้วแก้:

```env
CTFD_URL=http://10.31.7.218
CTFD_SESSION_COOKIE=<session จาก browser>
ANTHROPIC_API_KEY=sk-ant-...
```

### 3.4 ป้องกัน dashboard ด้วย token (ทางเลือก แนะนำถ้าเปิดให้คนอื่นเข้าถึงเครื่องได้)
Dashboard ไม่มี login มาให้ตั้งแต่แรก (ถือว่าอยู่บน `127.0.0.1` เท่านั้น) ถ้าอยากใส่ token กัน ให้ตั้งใน `.env`:

```env
WEBUI_TOKEN=<สุ่มมาสักชุด>
```

เมื่อตั้งแล้ว ทุก request ไปที่ `/api/*` ต้องแนบ `Authorization: Bearer <token>` — เปิดหน้าเว็บครั้งแรกจะเด้ง prompt ให้กรอก token แล้วจำไว้ใน browser ให้ (`localStorage`) ส่วน `ctf-msg` ใช้ `--token` หรือตั้ง env `WEBUI_TOKEN` ไว้ก่อนเรียกได้เลย ปล่อยว่างไว้ = ไม่มี auth (ค่า default)

### 3.5 จำกัดวงเงินรวม (ทางเลือก)
ตั้ง `.env`:

```env
MAX_TOTAL_COST_USD=20
```

เมื่อยอดรวมเกิน coordinator LLM และ dashboard จะขึ้นเตือน (banner สีแดง) แต่**ไม่ auto-kill swarm ที่รันอยู่** — ต้องกด Kill เองถ้าต้องการหยุด ปล่อยเป็น `0` = ไม่จำกัด (ค่า default)

---

## 4. รันระบบ

```bash
./run.sh
```

หรือแบบละเอียด:

```bash
./run.sh --no-build            # ข้าม build/เช็ค image
./run.sh --web-port 9400       # เปลี่ยน port dashboard
./run.sh --max-challenges 5    # จำกัด swarm พร้อมกัน
./run.sh --single /path/challenge   # แก้โจทย์ local โจทย์เดียว
```

หลังรัน → เปิด **http://127.0.0.1:9400**

---

## 5. ใช้งาน dashboard

### แถบบนสุด
| ปุ่ม | หน้าที่ |
|---|---|
| **Auto-spawn: OFF/ON** | OFF = รอคุณกด Spawn เอง, ON = spawn อัตโนมัติทุกโจทย์ใหม่ |
| **Logs** | ดู trace ของทุก agent ทุกโจทย์ (รวมที่จบไปแล้ว) |
| **Providers** | เพิ่ม/แก้/ลบ model providers |
| **Settings** | ตั้ง CTFd + ทดสอบการเชื่อมต่อ |

### KPI (แถวสถิติ)
CTFd / Cost / Tokens / Solved / Unsolved / Active swarms

### ตารางโจทย์
- **จุดไฟ + กราฟ** ข้างชื่อโจทย์: เขียวพัลส์ = agent กำลังทำงาน, เทา = idle
- **สถานะ**: solved / running / unsolved
- **ปุ่มต่อโจทย์**:
  - `Spawn swarm` — เริ่มแก้โจทย์นั้น (ทุก model ที่พร้อม)
  - `Trace` — ดู activity ของ agent แบบ live (refresh ทุก 2 วิ)
  - `Broadcast` — ส่ง hint ไปทุก agent ในโจทย์
  - `Bump` — ส่ง hint เจาะจงให้ agent ตัวเดียว
  - `Kill` — หยุด swarm + ลบ container ทันที
  - `Log` — ดู trace ล่าสุด (โจทย์ที่จบ/solve แล้ว)

### Chat กับ coordinator (CLI)
ถ้าอยากสั่ง coordinator ด้วยข้อความ:

```bash
./run.sh msg "spawn on challenge '01_กุญแจ'"
./run.sh msg "broadcast hint: flag format is FLAG{...}"
```

### "จนกว่า flag" — ให้ AI หาจนกว่าจะเจอ (auto-retry ต่อโจทย์)
เมื่อ swarm ของโจทย์ใดจบลงโดย**ไม่พบ flag** (solver หยุด/หมดทาง) ระบบจะ spawn พยายามใหม่ให้อัตโนมัติ — attempt ใหม่ context ใหม่พร้อมสรุปรอบก่อนที่บอกให้ลองวิธีที่ยังไม่ได้ลอง — วนไปจนกว่า: เจอ flag, กด Kill, กดปิด toggle, หรือถึงจำนวนรอบสูงสุด

- **เปิด**: กดปุ่ม **`⏳ flag`** บนแถวโจทย์ (ตอนกำลังรันหรือยังไม่เจอ flag) — ถ้าโจทย์ยังไม่มี swarm รันอยู่จะ spawn attempt แรกให้ทันที; ปุ่มจะแสดงเป็น **`⏳ flag ON (n)`** โดย `n` คือจำนวนรอบที่ผ่านไป
- **ดูงานระหว่างรอ**: เปิด **Trace** (refresh 2 วิ) เพื่อดู tool call/ผลลัพธ์ของ agent แต่ละตัว; จำนวนรอบ `attempt #n` เห็นจาก label บนปุ่ม ⏳ flag
- **จำนวนรอบสูงสุด**: ตั้งจาก `max_attempts_per_challenge` ใน `.env`/Settings (ค่า default `3`; ตั้ง `0` = ไม่จำกัด — หยุดโดยการกด Kill/ปิด toggle เอง)
- การ Kill จะปิด auto-retry ของโจทย์นั้นเสมอ (กันไม่ให้เด้งกลับมาวนใหม่โดยไม่ตั้งใจ)

### Spawn แบบแยกหน้าที่ (AI split roles)
ใน modal **Spawn swarm** ให้ติ๊ก **"Let AI split roles"** → ระบบจะให้ planner LLM อ่านโจทย์ (ชื่อ/category/description/ไฟล์) แล้วแบ่ง agent แต่ละตัวให้คนละกลยุทธ์ — แต่ละคนได้ system prompt ที่มี section "Your Role & Strategy" เฉพาะตัว (คนหนึ่งโฟกัส recon, อีกคนโฟกัส exploit ฯลฯ)

- **Agent count**: กำหนดจำนวน agent รวม (โมเดลเดียวกันซ้ำได้ — agent key เป็น `model#role`) `0` = หนึ่งตัวต่อโมเดลที่เลือก
- **Instruction** (optional): คำสั่งเพิ่มให้ planner เช่น "ให้ตัวหนึ่งโฟกัสฝั่ง network อีกตัววิเคราะห์ไฟล์"
- **ถ้าไม่มี planner model** (ไม่มี API key Anthropic/OpenAI/Gemini/custom) หรือคำตอบ planner ใช้ไม่ได้ → ระบบ fallback แจก role template ตาม category ให้อัตโนมัติ — spawn ได้เสมอ
- ตัวเลือกนี้เป็น opt-in: ไม่ติ๊ก = พฤติกรรมเดิม (หนึ่ง solver ต่อหนึ่งโมเดล)
- ดูงานแต่ละ agent ผ่าน **Trace** — รายชื่อ agent จะเป็น `model#role` เช่น `custom/Cloud/claude-fable-5#recon-enumeration`

### Skill Library (on-demand) + flag ไม่อยากหาย
- **Library**: import ท่า security ที่คัดมาแล้วลง `agent_skills/` (274 ท่า) ด้วย:
  ```bash
  uv run python import_skills.py            # คัดจาก ~/Downloads/Users/k1god/.agents/skills
  ```
  พอโฟลเดอร์ `agent_skills/` มีอยู่ ทุก sandbox จะ mount `/challenge/skills` (read-only) และ solver จะเห็น hint ในระบบ prompt ให้ **`grep INDEX.txt` → `cat <ชื่อ>.md`** เฉพาะท่าที่ต้องการ — ไม่ทำให้ context บวม เปิด/ปิดโดยมี/ไม่มีโฟลเดอร์
- **Flag ที่เจอจะไม่หาย**: เมื่อ swarm ยืนยัน flag ได้ ระบบเขียน `logs/flags.jsonl` (ts/challenge/model/flag) + log `FLAG FOUND` + แสดง flag (บรรทัดเขียว) ใต้ชื่อโจทย์บน dashboard — แก้กรณีที่ก่อนหน้าแก้โจทย์ได้แต่ flag ไม่เห็น

---

## 6. การแก้ปัญหา (ที่เจอบ่อย)

| อาการ | สาเหตุ | วิธีแก้ |
|---|---|---|
| `permission denied` Docker | user ไม่อยู่ใน docker group / session เก่า | `sudo usermod -aG docker $USER` → `newgrp docker` → restart |
| Test CTFd ได้ 401 | session cookie ผิด/หมดอายุ หรือมี token เก่าค้าง | เอา `session=` ล่าสุดจาก browser มาแทน; ล้างช่อง token |
| solver error "expected JSON data" | base URL ขาด `/v1` | แก้ base URL เป็น `.../v1` (ใน Providers → Edit) |
| solver error "'RunUsage' object is not callable" | รันด้วยโค้ดเก่า | restart (`pkill -f ctf-solve` → `./run.sh`) |
| Cost/Tokens เป็น 0 | ยังไม่มี solver รันเสร็จ หรือ custom model ไม่มีราคา | รอให้ solver ทำงาน; cost ของ custom เป็นค่าประมาณ |
| กราฟ/ปุ่มไม่ขึ้น | browser cache เก่า หรือโค้ดเก่า | hard-refresh (Ctrl+Shift+R) + restart |
| UI error "Unexpected token / function not defined" | cache เก่า | hard-refresh (Ctrl+Shift+R) |
| อยากเริ่มต้นใหม่ทั้งหมด | state เก่า | `./run.sh --reset` (ดูข้อ 7) |

---

## 7. รีเซ็ตกลับค่าเริ่มต้น

```bash
pkill -f "ctf-solve"          # หยุด coordinator
rm -f .env providers.json      # ลบ config
rm -rf logs challenges          # ลบ trace + โจทย์ที่ดาวน์โหลด
# ลบ container ค้าง
docker ps -aq --filter label=ctf-agent | xargs -r docker rm -f
./run.sh                       # เริ่มใหม่สะอาด (providers จะถูก seed เป็น default)
```

---

## 8. สถาปัตยกรรมโดยย่อ

```
CTFd ← poller (5s) → coordinator (LLM) ← dashboard (http://127.0.0.1:9400)
                          │
                 spawn swarm ต่อโจทย์
                          │
        ┌─────────────────┼─────────────────┐
     solver A          solver B         solver C   ← หลาย models แข่งกัน
        │                 │                 │
     Docker container  Docker container  Docker container  (แยก isolated)
```

- **Coordinator LLM** ดู trace solver แล้วช่วย bump/broadcast hint
- **swarm** = หลาย solver แข่งกัน ตัวแรกเจอ flag ชนะ ตัวอื่นถูกหยุด
- **trace** ทุก tool call ถูกบันทึก JSONL → ดูผ่าน Logs/Trace

---

## 9. ไฟล์/โฟลเดอร์ที่เกี่ยวข้อง

| ไฟล์ | หน้าที่ |
|---|---|
| `run.sh` | สคริปต์รันหลัก (install uv, uv sync, build image, รัน) |
| `sandbox/Dockerfile.sandbox` | image sandbox (Kali + CTF tools) |
| `providers.json` | รายการ model providers (จัดการผ่านเว็บ) |
| `.env` | การตั้งค่า (CTFd, API keys) |
| `logs/` | trace ของ solver ทุกตัว (JSONL) |
| `challenges/` | โจทย์ที่ดึงมาจาก CTFd |