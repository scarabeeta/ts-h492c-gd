# TS-H492C GD-ROM firmware

TS-H492C (IDE CD-RW/DVD-ROM) firmware for dumping Dreamcast GD-ROMs. Based on DE02. Current version: **GD2D**.

Only the TS-H492C. Other letters (TS-H492A, ...) are different drives. Tested only with Dell firmware (DE0x); retail units (Samsung SH-M522C) untested.

## Download

`TS-H492C_GD2D.bin`: https://archive.org/details/ts-h492c-gd2d

SHA-256 `6c8f27a5b49a224ab485908d9d193fc78090038bdc7a54fb73f44c73cb22ccd2`

Changes against DE02: [PATCHES.md](PATCHES.md).

## Flashing (Linux)

Native IDE port only (motherboard or PCI/PCIe IDE card), not USB. Needs Python 3 and access to the drive's `/dev/sgN` (`lsscsi -g`).

```
SGDEV=/dev/sgN python3 h492cflash.py read backup.bin           # back up first
SGDEV=/dev/sgN python3 h492cflash.py TS-H492C_GD2D.bin         # dry run
SGDEV=/dev/sgN python3 h492cflash.py TS-H492C_GD2D.bin go      # flash
```

- Reading the flash is slow: about 14 minutes each for the backup, the dry run, and the read-back after writing. The write itself takes about a minute.
- `go` saves the current flash to `h492cflash-backup-<time>.bin` before writing; add `nobackup` to skip that if you already have a backup.
- After writing, the drive restarts by itself and the tool compares the whole flash with the image.
- If a write fails, do not power-cycle the drive; run the same command again.
- To go back, flash your backup with `go force`.
- Reboot before dumping: Linux keeps the old revision until then.

## Dumping

With [dcdump](https://github.com/scarabeeta/dcdump):

```
dcdump --drive TS-H492C
```

By hand, LD area with redumper, HD area with dreamdump at 20x:

```
redumper disc --drive=/dev/sgN --drive-type=GENERIC --drive-read-method=BE \
  --drive-read-offset=6 --drive-sector-order=DATA_SUB_C2
dreamdump disc --drive=/dev/sgN --sector-order=DATA_SUB_C2 --read-offset=6 \
  --read-at-once=16 --speed=20
```

Normal CDs dump with the same redumper command.

## Known limits

- Tested on one drive.
- Burning is not tested. The changes do not touch the write path, so it should work as before.
- The HD area is limited to 20x; faster hangs the drive.
- redumper reads one sector per command, so a full CD takes about 20 minutes.
- libata sometimes drops the drive to PIO and dumps get about 3 times slower. `/sys/class/ata_device/dev*/xfer_mode` should say `XFER_UDMA_2`.

## Evidence

Dumps matching Redump:

1. Harusame Youbi (T-20106M), dcdump: all 3 tracks.
2. SLPM-86378 (PS1), redumper: 10 of 10 runs, disc reloaded before each.

Audio CD (redumper at 4x, 24x and max) and DVD (redumper) dumps are identical to the ones made with earlier versions.

## License

Copyright (C) 2026 scarabeeta

`h492cflash.py`, the documentation, and the changes to the firmware (listed in [PATCHES.md](PATCHES.md)): GPL-3.0-or-later (see `LICENSE`). The rest of the firmware image belongs to its rights holders and is not covered by this license.

## Disclaimer

Use at your own risk. I am not responsible for bricked drives or lost data.
