# TS-H492C GD-ROM firmware

Modified firmware that lets the TSSTcorp CDRWDVD TS-H492C (IDE CD-RW/DVD-ROM, common in Dell PCs) dump Dreamcast GD-ROMs. Based on the drive's DE02 firmware. Current version: **GD2D**.

Only the TS-H492C. Drives with another letter (TS-H492A, TS-H492B, ...) are different hardware and probably not compatible; untested. The flasher refuses them.

## Download

`TS-H492C_GD2D.bin`: <INTERNET ARCHIVE URL>

SHA-256 `6c8f27a5b49a224ab485908d9d193fc78090038bdc7a54fb73f44c73cb22ccd2`

## Flashing (Linux)

Native IDE port only (motherboard or PCI/PCIe IDE card), not USB. Needs Python 3 and root.

Put `h492c_flash.py` and `TS-H492C_GD2D.bin` in one directory:

```
sudo python3 h492c_flash.py              # dry run
sudo python3 h492c_flash.py --execute    # flash
```

- The drive is found by its model string; anything other than a TS-H492C is refused.
- The current flash is saved to `backup_<revision>_<time>.bin` first, and the whole flash is read back and compared after writing. About 30 minutes: reading the flash takes about 14 minutes each time (backup and verify); the write itself about 1 minute.
- `--no-backup` skips the backup read (about 14 minutes), for when you already have a backup. The read-back check always runs.
- Do not interrupt or power off while it writes. If a write fails, run the same command again.
- Reboot afterwards: Linux shows the old revision until then.
- To go back: `--image backup_....bin --allow-unknown --execute`.

## Dumping

dcdump does it all (needs a version that lists GD2D):

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

## Changes against DE02

Byte-level list: [PATCHES.md](PATCHES.md).

- HD area readable: out-of-range checks opened, minutes 100+ handled, long inward seeks go through a waypoint. Only for discs detected as GD-ROM (LD capacity below 45000), so normal CDs keep the stock paths.
- A bad GD-ROM spin-up is retried; the result is readable so dcdump can refuse a bad state.
- READ CD with expected type CD-DA on a data track returns the raw scrambled sector, as redumper needs. Stock rejected it (05/64).
- No read-ahead resume. Stock returns the subchannel 2 frames late after the buffer fills.
- Stock bug fixed: a raw read could get sectors the data engine had prefetched (descrambled, shifted) with GOOD status.
- Stock bug fixed: READ CD over 64 KB with subchannel/C2 hung the drive.
- HD area limited to 20x; faster hangs the drive.
- Memory window through REQUEST SENSE: XRAM 0x8000-0x8BFF readable (`03 <hi> 20 <lo> 12 00`); only the 16 switch bytes 0x8BB0-0x8BBF writable (`03 8B 21 <lo> 12 <value>`). All switches are 0 at power-on, which is the tested setting; they turn the changes above off for testing.

## Known limits

- Tested on one drive and two discs only. Audio CD, DVD and burning not tested yet on GD2D.
- redumper reads one sector per command, so a full 70-minute CD takes about 20 minutes whatever the speed setting.
- Data-mode READ CD (expected type not CD-DA) is slow: about 3x, 1.5x with subchannel.
- Discs with a weak signal keep the stock 24x limit.
- libata sometimes drops the drive to PIO and dumps get about 3 times slower. Check `/sys/class/ata_device/dev*/xfer_mode`; it should be `XFER_UDMA_2`.

## Evidence

Dumps matching Redump, on GD2D:

1. Harusame Youbi (T-20106M), dcdump: all 3 tracks and the cue, 13 minutes.
2. SLPM-86378 (PS1), redumper, 10 runs with a disc reload before each: 10/10, 20 minutes each.

## License

`h492c_flash.py` and this text: GPL-3.0-or-later. The firmware image is not in this repository.
