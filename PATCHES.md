# GD2D patches

GD2D vs. the drive's DE02 firmware: 1643 bytes in 110 places. New code sits in 0xFF-filled space: common 0x20DB-0x27AC and 0xFB80-0xFC06, bank 5 0xFD00, bank 6 0xD880-0xD9F5.

## Addressing

MediaTek MT1685, 8051 with code banking. 512 KiB SPI flash.

| Code | File offset |
|---|---|
| 0x0000-0xFFFF (common, bank 0) | a |
| bank n 0x2800-0xFFFF (n = 1..9) | n * 0xD800 + a |

0x0000-0x27FF is the same in every bank. Bank 9 ends at file 0x7FFFF; 0x7FFE0-0x7FFFF is the trailer (model, revision, block table, checksum).

Checksum: big-endian 16-bit word at 0x7FFFE = byte sum of 0x00000-0x7FFFD plus a constant. A patch moves it by its own byte-sum delta.

## Stock code used

| Address | Function |
|---|---|
| 0x0B32 | speed change entry, target step in R7 (0x14 = 20x, 0x30 = 48x) |
| 0x1474 | seek executor -> bank6 0xB5B8 |
| 0x9805 / 0x9841 | READ CD audio path / data-track raw path |
| 0xB2F7 | READ(10)/(12) exec. LBA from CDB in XRAM 0x8494-0x8497 |
| 0x964C | READ CD exec |
| XRAM 0x802C-0x802F | capacity (LD lead-out + 149) |
| XRAM 0x8492 / 0x8493 | CDB[0] / CDB[1] (READ CD expected sector type in bits 2-4) |
| IRAM 0x4D / 0x50 | current / target minute |
| bank5 0x8416-0x8739 | seek planner entry / exit |
| bank5 0xE62A-0xE6F1 | CD spin-up attempt |
| bank6 0x6078 | raw (CD-DA) engine |
| XRAM 0x40A1-0x40A3 | hardware target M:S:F register. Normalises a valid-BCD write, so minute 100 (0x64 binary) can't be written as binary |
| XRAM 0x40BE/BF, 0x40C0/C1 | hardware buffer counts |
| bank6 0x647C | raw engine read-ahead resume |
| bank6 0xB41D | buffer hit test, shared by both engines. Miss path 0xB4D1 (cold start) |

## Changes

| File | Code | Bytes | Change | Since |
|---|---|---|---|---|
| 0x02903 | 0x2903 | 4 | INQUIRY revision `DE02` -> `GD2D` | GD01 |
| 0x08FE6 0x0A71B | 0x8FE6 0xA71B | 2 x 3 | Read accept gates: out-of-range (05/21) -> `LJMP` to the handler's own read entry | GD01 |
| 0x0989D 0x09DC8 0x0AF02 0x0B412 0x0B437 0x0B44E 0x0DA36 | same | 7 x 3 | `JNB ACC.6` (hardware out-of-range bit) -> `SJMP` to the in-range target | GD01 |
| 0x0F967 | 0xF967 | 1 | Capacity compare `JNC` -> `SJMP` | GD01 |
| 0x0B3D3 | 0xB3D3 | 8 | READ exec: status 1 and status >= 5 rejects (05/64) NOPed. HD LBAs have no LD TOC entry | GD02 |
| 0x0B34A 0x096E4 | 0xB34A 0x96E4 | 6 + 3 | LBA load in the READ(10)/(12) and READ CD execs -> `LCALL 0x20DB` | GD0E |
| 0x020DB | 0x20DB | 86 | GD-ROM only (0x24A0), opcode 28/A8/BE, LBA >= 44850: LBA + 0xE0000000. The 0xE0 top byte is the drive's own direct (TOC-less) position | GD0E, GD0J, GD1R |
| 0x09883 | 0x9883 | 3 | READ CD status >= 5: `LJMP 0x9841` (raw read) instead of 05/64 | GD0F |
| 0x09873 | 0x9873 | 7 | READ CD status >= 5 -> `LJMP 0x22A0`: expected type CD-DA -> raw engine via 0x9805 with the 0xE0 mark stripped; else data engine | GD1I, GD1L |
| 0x09837 | 0x9837 | 3 | CD-DA requested on a data track -> `LJMP 0x24F8`: raw scrambled sector instead of 05/64. redumper reads this way | GD1S |
| 0x5515E 0x553C0 0x55AFD | bank6 0x415E 0x43C0 0x4AFD | 3 x 3 | Data engine target write -> 0x2200 / 0x2210 / 0x2270: minute >= 100 written to 0x40A1 as extended BCD (100 = 0xA0), binary minute kept | GD1G |
| 0x5707A 0x57200 0x575B8 | bank6 0x607A 0x6200 0x65B8 | 3 x 3 | The same on the raw engine -> 0x2300 / 0x2310 / 0x2370 | GD1J |
| 0x55A48 0x5752E | bank6 0x4A48 0x652E | 2 x 3 | 0x40A1 read-back -> 0x2440 / 0x2460: an extended-BCD minute (>= 0xA0) is decoded, then 0x2231 / 0x2331 replace the hardware-mangled echo with the kept minute. Fixes the resume after a full buffer past minute 100 | GD1G, GD1N |
| 0x5CBC3 0x5CD18 0x5CD97 0x5CDAA 0x5CDD9 | bank6 0xBBC3 0xBD18 0xBD97 0xBDAA 0xBDD9 | 5 x 4 | Seek executor per-minute tables (120 entries at 0x2800 / 0x28F0): index = min(minute, 119) (`LCALL 0x2400`) | GD1K |
| 0x5C5DA 0x5C5E5 0x5C5F6 0x5C601 | bank6 0xB5DA 0xB5E5 0xB5F6 0xB601 | 4 x 2 | Lead-in classifier calls 0x12A0 / 0x12A6 -> 0x2410 / 0x2420: minutes > 99 returned unchanged (stock clamps them to 99, i.e. lead-in) | GD1M |
| 0x31670 | bank3 0x8E70 | 3 | Position decoder, TNO 0 branch -> 0x24C0: on a GD-ROM, Q relative time >= 141:29:00 (HD lead-in) is reported as absolute rel - 141:29:00. Stock reports 0:00 there and the seek bounces | GD1R |
| 0x02480 | 0x2480 | 3 | GD-ROM test -> 0x25F0: 0 < capacity < 45000. Every GD-only rule calls this first | GD25 |
| 0x4BCA2 | bank5 0x84A2 | 3 | Seek planner -> 0x2586: GD-ROM, current and target minute >= 10, inward, target < 30, distance >= 35 minutes: aim at 40:00:00 first (0x2170, relay flag 0x8B75) | GD1V, GD22, GD23 |
| 0x4BF39 | bank5 0x8739 | 3 | Planner exit -> 0x21C0: if the relay was used, restore the real target and restart the planner once (`LJMP 0x8416`) | GD22 |
| 0x4BC16 | bank5 0x8416 | 4 | Planner entry -> `LCALL 0x21F0`: clear the relay flag | GD22 |
| 0x51E87 | bank5 0xE687 | 10 | Spin-up -> `LCALL 0x2770`: a CD whose first spin-up pass succeeded is sent once per medium through the stock low-level retry, which runs the servo auto-adjusts. Without them HD seeks fail or take 3-30 s on about 2 spin-ups in 3 | GD1Z |
| 0x0B0FB | 0xB0FB | 5 | New-medium event -> `LCALL 0x2750`: re-arm the once-per-medium guard (0x8B8A) | GD1Z |
| 0x52A53 | bank5 0xF253 | 4 | Spin-up level measurement -> `LCALL 0x2730`: keep the level (0x8B86) | GD1Z |
| 0x51E2A 0x51EF1 | bank5 0xE62A 0xE6F1 | 4 + 3 | Spin-up start / end -> 0x25B0 / 0x25C0: status byte 0x8B78 cleared, then written (bit 7 valid, bit 0 low-level path ran, bit 1 promoted, bit 2 promoted and failed, bit 3 failed). dcdump reads it | GD24 |
| 0x513D2 | bank5 0xDBD2 | 4 | Disc-state reset -> `LCALL 0xFD00`: clear 0x8B78 too (a DVD spin-up skips 0xE62A) | GD27 |
| 0x3DC64 | bank4 0x7C64 | 6 | Stock 24x ceiling for low-level discs -> `LCALL 0x2614`: skipped after a successful promoted spin-up (the promotion sets the low-level bit on every CD) | GD29 |
| 0x551D8 0x570A9 | bank6 0x41D8 0x60A9 | 2 x 1 | Sectors per PIO DRQ block = limit / 11 - 1 instead of / 9 - 1. With subchannel/C2 (up to 2742 B/sector) one block passed 0xFFFF bytes and the command hung | GD28 |
| 0x5C44E | bank6 0xB44E | 2 | Hit test target `LCALL 0x1E64` -> 0x2634: ignore the 0xE0 HD mark, so HD data-mode reads hit the buffer | GD2A |
| 0x00B32 | 0x0B32 | 3 | Speed change -> 0x2501: on a GD-ROM, step and ceilings 0x8731 / 0x861A <= 0x14 (20x). At 24x+ the HD read hangs. Off: 0x8BBA bit 0. Count 0x8BBF | GD2C |
| 0x5747C | bank6 0x647C | 3 | Raw engine resume -> 0xD8C0: if the buffer still holds sectors (0x40BE/BF != 0), do not resume; set PAUSED (0x8BC8). 0x40BE = 0xFF counts as empty, as in stock. A resume returns the subchannel 2 frames late; a cold start does not. Off: 0x8BB0 bit 0 | GD2C |
| 0x5C4B6 | bank6 0xB4B6 | 3 | Hit test -> 0xD900: hit with 0x40BE/BF = 0 and 0x40C0/C1 != 0 becomes a miss (counts 0x8BCA, 0x8BC9). While PAUSED, hit only if the whole command is buffered. Optional guard 0x40BE/BF < 0x40C0/C1: 0x8BB0 bit 1 (off by default) | GD2C |
| 0x5C41D | bank6 0xB41D | 3 | Hit test entry -> 0xD9B0: record the requesting engine (0x8BD0: 1 raw, 2 data) from the return address | GD2C |
| 0x5C48E | bank6 0xB48E | 3 | Hit decision -> 0xD9C6: buffer filled by the other engine -> miss (count 0x8BD2). Stock let a CD-DA read take the data engine's descrambled prefetch with GOOD status. Off: 0x8BBA bit 1 | GD2C |
| 0x5C4D1 | bank6 0xB4D1 | 3 | Miss -> 0xD9ED: buffer owner (0x8BD1) = requester, clear PAUSED, then the stock cold start | GD2C |
| 0x5E880 | bank6 0xD880 | 47 | Event ring, 64 x 4 bytes at XRAM 0x8200, next slot 0x80FC: [type, IRAM 0x5E, 0x5F, 0x40C1]. Types: 1 resume skipped, 2 miss, 3 stream start, 4 guard, 5 owner mismatch, 6 0x40BE = 0xFF start | GD2C |
| 0x0AAA0 | 0xAAA0 | 3 | REQUEST SENSE -> 0xFB80: `03 <hi> 20 <lo> 12 00` returns XRAM 0x8000-0x8BFF (4 bytes in the sense information field); `03 00 22 <lo> 12 00` IRAM; `03 8B 21 <lo> 12 <v>` writes XRAM 0x8BB0-0x8BBF only. Hardware registers 0x4000-0x4FFF are never read. Normal REQUEST SENSE unchanged | GD1Y, GD2C |
| 0x7FFE8 | trailer | 4 | Trailer revision `DE02` -> `GD2D` | GD01 |
| 0x7FFFE | trailer | 2 | Checksum | |

Every GD rule checks the GD-ROM test (0x2480) first, so CDs and DVDs run stock code there. The changes not tied to GD-ROMs: CD-DA on data tracks (0x9837), the spin-up promotion and its status byte, the DRQ block size, the read-ahead and buffer-owner rules, and the memory window.

## Switches

XRAM, 0 at power-on = the tested setting. Set with `03 8B 21 <lo> 12 <value>`.

| Byte | Bit | 1 = |
|---|---|---|
| 0x8BB0 | 0 | stock read-ahead resume |
| 0x8BB0 | 1 | extra guard on |
| 0x8BB0 | 2 | empty-buffer guard off |
| 0x8BBA | 0 | 20x GD limit off |
| 0x8BBA | 1 | buffer owner check off |
