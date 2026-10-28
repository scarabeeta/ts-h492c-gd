#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Flash a firmware image to a TSSTcorp TS-H492C (Linux, native IDE/PATA).

Put this script and the firmware image (e.g. TS-H492C_GD2D.bin) in one directory, then:

    sudo python3 h492c_flash.py                 # show the plan, send nothing
    sudo python3 h492c_flash.py --execute       # back up, write, read back, verify

Only the TS-H492C is supported. Other suffixes (TS-H492A, TS-H492B, ...) are different drives
and are refused.

Steps with --execute:
  1. find the drive by INQUIRY (vendor TSSTcorp, product "CDRWDVD TS-H492C")
  2. read the current firmware into backup_<revision>_<time>.bin next to this script
     (skipped with --no-backup; reading the flash takes about 14 minutes)
  3. write the image with the drive's own update commands (same sequence as the official
     TSST/Dell updater)
  4. wait for the drive, read the whole flash back and compare it with the image

Never interrupt step 3 and never power off during it: a half-written flash does not boot.
Ctrl+C is ignored while writing.
"""
import argparse, ctypes, fcntl, glob, hashlib, os, signal, sys, time

VERSION = "1.1"
FLASH_SIZE = 0x80000
VENDOR, PRODUCT = "TSSTcorp", "CDRWDVD TS-H492C"

# Images this tool accepts without --allow-unknown (sha256 -> description).
KNOWN = {
    "6c8f27a5b49a224ab485908d9d193fc78090038bdc7a54fb73f44c73cb22ccd2": "GD2D (GD-ROM firmware)",
    "ff3a1ee46e127905ff06d045260e39a77fcd91033cd8544fdf8394874501009a": "DE03 (stock, Dell R148011)",
    "9e85ff686e9e68187b0bdd9aa5fbaa11dfa6f4bc7609a4c6cadb43e8279cac2c": "DE04 (stock, Dell R170389)",
}

SG_IO = 0x2285
DXFER_NONE, DXFER_TO_DEV, DXFER_FROM_DEV = -1, -2, -3


class SgIoHdr(ctypes.Structure):
    _fields_ = [("interface_id", ctypes.c_int), ("dxfer_direction", ctypes.c_int),
                ("cmd_len", ctypes.c_ubyte), ("mx_sb_len", ctypes.c_ubyte),
                ("iovec_count", ctypes.c_ushort), ("dxfer_len", ctypes.c_uint),
                ("dxferp", ctypes.c_void_p), ("cmdp", ctypes.c_void_p), ("sbp", ctypes.c_void_p),
                ("timeout", ctypes.c_uint), ("flags", ctypes.c_uint), ("pack_id", ctypes.c_int),
                ("usr_ptr", ctypes.c_void_p), ("status", ctypes.c_ubyte),
                ("masked_status", ctypes.c_ubyte), ("msg_status", ctypes.c_ubyte),
                ("sb_len_wr", ctypes.c_ubyte), ("host_status", ctypes.c_ushort),
                ("driver_status", ctypes.c_ushort), ("resid", ctypes.c_int),
                ("duration", ctypes.c_uint), ("info", ctypes.c_uint)]


class Result:
    def __init__(self, ok, data=b"", sense=b"", info=""):
        self.ok, self.data, self.sense, self.info = ok, data, sense, info

    @property
    def sense_key(self):
        return self.sense[2] & 0x0F if len(self.sense) > 2 else None


def scsi(fd, cdb, direction=DXFER_NONE, out=b"", inlen=0, timeout_ms=5000):
    n = len(out) if direction == DXFER_TO_DEV else inlen
    buf = ctypes.create_string_buffer(bytes(out), max(n, 1)) if direction == DXFER_TO_DEV \
        else ctypes.create_string_buffer(max(n, 1))
    sense = ctypes.create_string_buffer(32)
    cdb_b = ctypes.create_string_buffer(bytes(cdb), len(cdb))
    h = SgIoHdr()
    h.interface_id = ord("S")
    h.dxfer_direction = direction if n else DXFER_NONE
    h.cmd_len, h.mx_sb_len, h.dxfer_len = len(cdb), 32, n
    h.dxferp = ctypes.cast(buf, ctypes.c_void_p) if n else None
    h.cmdp = ctypes.cast(cdb_b, ctypes.c_void_p)
    h.sbp = ctypes.cast(sense, ctypes.c_void_p)
    h.timeout = timeout_ms
    try:
        fcntl.ioctl(fd, SG_IO, h)
    except OSError as e:
        return Result(False, info=f"ioctl error {e.errno}")
    sb = sense.raw[:h.sb_len_wr]
    if h.status or h.host_status or h.driver_status:
        return Result(False, buf.raw[:n - h.resid], sb,
                      f"status {h.status:#x} host {h.host_status:#x} driver {h.driver_status:#x}"
                      f" sense {sb[:18].hex(' ')}")
    return Result(True, buf.raw[:n - h.resid] if direction == DXFER_FROM_DEV else b"", sb, "GOOD")


def inquiry(fd):
    r = scsi(fd, [0x12, 0, 0, 0, 36, 0], DXFER_FROM_DEV, inlen=36)
    if not r.ok or len(r.data) < 36:
        return None
    d = r.data
    return (d[8:16].decode("ascii", "replace").strip(), d[16:32].decode("ascii", "replace").strip(),
            d[32:36].decode("ascii", "replace").strip())


def is_h492c(ident):
    return ident is not None and ident[0] == VENDOR and ident[1] == PRODUCT


def candidates():
    """sg nodes whose sysfs vendor/model say TS-H492C (no command is sent to other devices)."""
    out = []
    for d in sorted(glob.glob("/sys/class/scsi_generic/sg*")):
        try:
            v = open(d + "/device/vendor").read().strip()
            m = open(d + "/device/model").read().strip()
        except OSError:
            continue
        if v == VENDOR and m == PRODUCT:
            out.append("/dev/" + os.path.basename(d))
    return out


def open_drive(dev):
    fd = os.open(dev, os.O_RDWR)
    ident = inquiry(fd)
    if not is_h492c(ident):
        os.close(fd)
        sys.exit(f"{dev}: INQUIRY says {ident}, not {VENDOR} {PRODUCT}. Refusing.")
    return fd, ident


def find_drive(dev_arg):
    if dev_arg:
        return dev_arg
    c = candidates()
    if not c:
        sys.exit(f"No {PRODUCT} found. Only the TS-H492C is supported (other suffixes are different"
                 " drives). Is it on a native IDE port and is the sg module loaded?")
    if len(c) > 1:
        sys.exit(f"More than one TS-H492C found ({', '.join(c)}); choose one with --dev.")
    return c[0]


def check_image(path, allow_unknown):
    img = open(path, "rb").read()
    sha = hashlib.sha256(img).hexdigest()
    if len(img) != FLASH_SIZE:
        sys.exit(f"{path}: {len(img)} bytes, a TS-H492C image is {FLASH_SIZE} bytes.")
    tag = img[0x7FFE0:0x7FFE8]
    rev = img[0x7FFE8:0x7FFEC].decode("ascii", "replace")
    if tag != b"TS-H492C" or img.find(b"TSSTcorpCDRWDVD TS-H492C" + img[0x7FFE8:0x7FFEC]) < 0:
        sys.exit(f"{path}: not a TS-H492C firmware image (identity strings missing).")
    bs_kib, count = img[0x7FFEC], img[0x7FFED]
    if (count - 1) * (bs_kib << 10) >= FLASH_SIZE or count < 2:
        sys.exit(f"{path}: bad block table ({bs_kib} KiB x {count}).")
    if sha not in KNOWN and not allow_unknown:
        sys.exit(f"{path}: sha256 {sha} is not a known release. Use --allow-unknown only for a"
                 " backup made by this tool or another image you trust.")
    return img, sha, rev


def read_flash(fd, label, progress=True):
    """Whole flash via the vendor read F2 02 (SPI READ), 64 bytes per command."""
    out = bytearray()
    step = 64
    for addr in range(0, FLASH_SIZE, step):
        cdb = [0xF2, 0x02, 0x00, (addr >> 16) & 0xFF, (addr >> 8) & 0xFF, addr & 0xFF,
               0x00, 0x00, step, 0x00]
        r = scsi(fd, cdb, DXFER_FROM_DEV, inlen=step, timeout_ms=5000)
        if not r.ok or len(r.data) != step:
            raise RuntimeError(f"{label}: read failed at {addr:#x}: {r.info}")
        out += r.data
        if progress and addr % 0x8000 == 0:
            print(f"\r  {label}: {addr * 100 // FLASH_SIZE:3d}%", end="", flush=True)
    if progress:
        print(f"\r  {label}: 100%")
    return bytes(out)


def write_plan(img):
    bs = img[0x7FFEC] << 10
    count = img[0x7FFED]
    plan = [("unlock", [0xFF, 0xAA, 0xBB, 0, 0, 0, 0, 0, 0, 0], b""),
            ("setup", [0xF1, 0x01, 0x00, 0x00, 0x4A, 0x82, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00], b"")]
    off = 0
    for i in range(count):
        last = i == count - 1
        n = len(img) - off if last else bs
        cdb5 = 0x00 if i == 0 else ((n >> 10) if last else 0xFF)
        plan.append((f"block {i + 1}/{count}", [0xFF, 0x00, 0x01, 0x00, 0x00, cdb5, 0, 0, 0, 0, 0, 0],
                     img[off:off + n]))
        off += n
    assert off == len(img)
    return plan


def wait_ready(dev, seconds=180):
    t0 = time.time()
    while time.time() - t0 < seconds:
        try:
            fd = os.open(dev, os.O_RDWR)
        except OSError:
            time.sleep(3)
            continue
        if scsi(fd, [0, 0, 0, 0, 0, 0]).ok and is_h492c(inquiry(fd)):
            return fd
        scsi(fd, [0x1B, 0, 0, 0, 1, 0], timeout_ms=30000)   # START UNIT
        os.close(fd)
        time.sleep(3)
    return None


def main():
    ap = argparse.ArgumentParser(description="TS-H492C firmware flasher " + VERSION)
    ap.add_argument("--image", help="firmware image (default: the one known image next to this script)")
    ap.add_argument("--dev", help="sg node of the drive (default: found automatically)")
    ap.add_argument("--execute", action="store_true", help="really write (default: show the plan only)")
    ap.add_argument("--backup-only", action="store_true", help="only save the current firmware")
    ap.add_argument("--no-backup", action="store_true",
                    help="skip the backup read (saves about 14 minutes; keep an earlier backup)")
    ap.add_argument("--allow-unknown", action="store_true", help="accept an image that is not a known release")
    a = ap.parse_args()
    if a.no_backup and a.backup_only:
        sys.exit("--no-backup and --backup-only together make no sense.")

    if os.geteuid() != 0:
        sys.exit("Run as root (sudo): the drive is accessed through /dev/sg*.")
    here = os.path.dirname(os.path.abspath(__file__))
    dev = find_drive(a.dev)
    fd, ident = open_drive(dev)
    print(f"Drive: {dev}  {ident[0]} {ident[1]}  firmware {ident[2]}")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    if a.backup_only:
        fw = read_flash(fd, "backup")
        path = os.path.join(here, f"backup_{ident[2]}_{stamp}.bin")
        open(path, "wb").write(fw)
        print(f"Saved {path}\n  sha256 {hashlib.sha256(fw).hexdigest()}")
        return 0

    if a.image:
        path = a.image
    else:
        found = [p for p in sorted(glob.glob(os.path.join(here, "*.bin")))
                 if hashlib.sha256(open(p, "rb").read()).hexdigest() in KNOWN]
        if len(found) != 1:
            sys.exit("Put exactly one release image (e.g. TS-H492C_GD2D.bin) next to this script,"
                     " or pass --image.")
        path = found[0]
    img, sha, rev = check_image(path, a.allow_unknown)
    print(f"Image: {path}\n  revision {rev}, sha256 {sha}\n  {KNOWN.get(sha, 'not a known release')}")
    plan = write_plan(img)
    first = "skip the backup" if a.no_backup else f"back up the current firmware ({ident[2]})"
    print(f"Plan: {first}, write {len(plan) - 2} blocks, read back and compare.")
    if not a.execute:
        print("Nothing was sent. Run again with --execute to flash.")
        return 0

    # 1. backup
    if a.no_backup:
        bpath = None
        print("  no backup (--no-backup)")
    else:
        fw = read_flash(fd, "backup")
        bpath = os.path.join(here, f"backup_{ident[2]}_{stamp}.bin")
        open(bpath, "wb").write(fw)
        print(f"  saved {bpath} (sha256 {hashlib.sha256(fw).hexdigest()[:16]}...)")
        if fw == img:
            print("The drive already has this exact firmware. Nothing to do.")
            return 0

    # 2. write; termination signals are held until the last block has been sent
    print("Writing. Do not power off or interrupt (about 1-2 minutes).")
    held = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT, signal.SIGTSTP}
    signal.pthread_sigmask(signal.SIG_BLOCK, held)
    try:
        for i, (name, cdb, data) in enumerate(plan):
            r = scsi(fd, cdb, DXFER_TO_DEV if data else DXFER_NONE, out=data, timeout_ms=15000)
            last = i == len(plan) - 1
            if r.ok:
                print(f"  {name}: GOOD", flush=True)
            elif name == "setup":
                print("  setup: rejected (normal, the official updater ignores it too)", flush=True)
            elif last:
                # The drive starts committing the new firmware while the last block is still
                # being acknowledged, so this command usually ends in an error. The read-back
                # below decides whether the write worked.
                print(f"  {name}: no clean status (normal for the last block)", flush=True)
            else:
                print(f"  {name}: FAILED ({r.info})", flush=True)
                restore = (f", or with --image {bpath} --allow-unknown --execute to restore the"
                           " backup" if bpath else "")
                print("\nThe write stopped in the middle. Do NOT power off. Run this tool again with"
                      f" --execute to rewrite{restore}.", file=sys.stderr)
                return 1
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        signal.pthread_sigmask(signal.SIG_UNBLOCK, held)

    # 3. read back
    print("Waiting for the drive to restart...")
    time.sleep(20)
    fd = wait_ready(dev)
    if fd is None:
        print("The drive did not come back within 3 minutes. Do NOT power off. Check dmesg, then run"
              " this tool with --backup-only to see what is in the flash.", file=sys.stderr)
        return 1
    rb = read_flash(fd, "verify")
    os.close(fd)
    if rb != img:
        bad = sum(1 for x, y in zip(rb, img) if x != y)
        print(f"VERIFY FAILED: {bad} bytes differ. Do NOT power off; run --execute again.",
              file=sys.stderr)
        return 1
    ident2 = inquiry(os.open(dev, os.O_RDWR))
    print(f"VERIFY OK: the flash equals the image (sha256 {sha[:16]}...).")
    print(f"Drive now reports firmware {ident2[2] if ident2 else '?'}.")
    print("Reboot before dumping: Linux shows the old revision until the drive is identified again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
