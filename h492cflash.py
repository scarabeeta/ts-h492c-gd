#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# h492cflash - firmware flasher for the TSSTcorp TS-H492C (native IDE), Linux.
USAGE = '''usage: SGDEV=/dev/sgN h492cflash.py read <out.bin>                  read the whole flash (512 KiB)
       SGDEV=/dev/sgN h492cflash.py <image.bin>                     dry run: compare, write nothing
       SGDEV=/dev/sgN h492cflash.py <image.bin> go [nobackup] [force] write, then read back and compare'''
import ctypes, errno, fcntl, hashlib, os, signal, sys, time

FLASH = 0x80000
VENDOR, PRODUCT = 'TSSTcorp', 'CDRWDVD TS-H492C'
KNOWN = {
    '6c8f27a5b49a224ab485908d9d193fc78090038bdc7a54fb73f44c73cb22ccd2': 'GD2D',
    'ff3a1ee46e127905ff06d045260e39a77fcd91033cd8544fdf8394874501009a': 'DE03 (Dell)',
    '9e85ff686e9e68187b0bdd9aa5fbaa11dfa6f4bc7609a4c6cadb43e8279cac2c': 'DE04 (Dell)',
}
SG_IO = 0x2285
NONE, TO_DEV, FROM_DEV = -1, -2, -3


class SgIoHdr(ctypes.Structure):
    _fields_ = [('interface_id', ctypes.c_int), ('dxfer_direction', ctypes.c_int),
                ('cmd_len', ctypes.c_ubyte), ('mx_sb_len', ctypes.c_ubyte),
                ('iovec_count', ctypes.c_ushort), ('dxfer_len', ctypes.c_uint),
                ('dxferp', ctypes.c_void_p), ('cmdp', ctypes.c_void_p), ('sbp', ctypes.c_void_p),
                ('timeout', ctypes.c_uint), ('flags', ctypes.c_uint), ('pack_id', ctypes.c_int),
                ('usr_ptr', ctypes.c_void_p), ('status', ctypes.c_ubyte),
                ('masked_status', ctypes.c_ubyte), ('msg_status', ctypes.c_ubyte),
                ('sb_len_wr', ctypes.c_ubyte), ('host_status', ctypes.c_ushort),
                ('driver_status', ctypes.c_ushort), ('resid', ctypes.c_int),
                ('duration', ctypes.c_uint), ('info', ctypes.c_uint)]


def scsi(fd, cdb, direction=NONE, out=b'', inlen=0, timeout_ms=5000):
    """Returns (ok, data, description)."""
    n = len(out) if direction == TO_DEV else inlen
    buf = ctypes.create_string_buffer(bytes(out), max(n, 1)) if direction == TO_DEV \
        else ctypes.create_string_buffer(max(n, 1))
    sense = ctypes.create_string_buffer(32)
    c = ctypes.create_string_buffer(bytes(cdb), len(cdb))
    h = SgIoHdr(interface_id=ord('S'), dxfer_direction=direction if n else NONE, cmd_len=len(cdb),
                mx_sb_len=32, dxfer_len=n, timeout=timeout_ms)
    h.dxferp = ctypes.cast(buf, ctypes.c_void_p) if n else None
    h.cmdp = ctypes.cast(c, ctypes.c_void_p)
    h.sbp = ctypes.cast(sense, ctypes.c_void_p)
    try:
        fcntl.ioctl(fd, SG_IO, h)
    except OSError as e:
        return False, b'', 'ioctl error %d' % e.errno
    ok = not (h.status or h.host_status or h.driver_status)
    data = buf.raw[:n - h.resid] if direction == FROM_DEV else b''
    return ok, data, 'GOOD' if ok else 'st%d h%d d%d sense %s' % (
        h.status, h.host_status, h.driver_status, sense.raw[:h.sb_len_wr][:18].hex(' '))


def inquiry(fd):
    ok, d, _ = scsi(fd, [0x12, 0, 0, 0, 36, 0], FROM_DEV, inlen=36)
    if not ok or len(d) < 36:
        return None
    return tuple(d[a:b].decode('latin1').strip() for a, b in ((8, 16), (16, 32), (32, 36)))


def check_image(img):
    """Returns a list of reasons the image does not look like TS-H492C firmware."""
    why = []
    if img[0x7FFE0:0x7FFE8] != b'TS-H492C' or b'TSSTcorpCDRWDVD TS-H492C' + img[0x7FFE8:0x7FFEC] not in img:
        why.append('TS-H492C identity strings missing')
    bs, count = img[0x7FFEC], img[0x7FFED]
    if count < 2 or (count - 1) * (bs << 10) >= FLASH:
        why.append('bad block table (%d KiB x %d)' % (bs, count))
    return why


def read_flash(fd, label):
    out = bytearray()
    for a in range(0, FLASH, 64):
        ok, d, desc = scsi(fd, [0xF2, 0x02, 0, a >> 16, (a >> 8) & 0xFF, a & 0xFF, 0, 0, 64, 0], FROM_DEV, inlen=64)
        if not ok or len(d) != 64:
            sys.exit('%s: flash read failed at 0x%X: %s' % (label, a, desc))
        out += d
        if a % 0x8000 == 0:
            print('\r  %s %3d%%' % (label, a * 100 // FLASH), end='', flush=True)
    print('\r  %s 100%%' % label, flush=True)
    return bytes(out)


def write_plan(img):
    bs, count = img[0x7FFEC] << 10, img[0x7FFED]
    plan = [('unlock', [0xFF, 0xAA, 0xBB, 0, 0, 0, 0, 0, 0, 0], b''),
            ('setup', [0xF1, 0x01, 0, 0, 0x4A, 0x82, 0, 0, 0, 0x01, 0, 0], b'')]
    off = 0
    for i in range(count):
        last = i == count - 1
        n = len(img) - off if last else bs
        c5 = 0 if i == 0 else (n >> 10 if last else 0xFF)
        plan.append(('block %d/%d' % (i + 1, count), [0xFF, 0x00, 0x01, 0, 0, c5, 0, 0, 0, 0, 0, 0], img[off:off + n]))
        off += n
    return plan


def wait_ready(dev, seconds=180):
    t0 = time.time()
    while time.time() - t0 < seconds:
        try:
            fd = os.open(dev, os.O_RDWR)
        except OSError:
            time.sleep(3)
            continue
        if scsi(fd, [0, 0, 0, 0, 0, 0])[0] and (inquiry(fd) or ())[:2] == (VENDOR, PRODUCT):
            return fd
        scsi(fd, [0x1B, 0, 0, 0, 1, 0], timeout_ms=30000)
        os.close(fd)
        time.sleep(3)
    return None


def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help') or (args[0] == 'read' and len(args) != 2):
        sys.exit(USAGE)
    dev = os.environ.get('SGDEV')
    if not dev:
        sys.exit('set SGDEV to the drive, e.g. SGDEV=/dev/sg2 (see lsscsi -g)\n' + USAGE)
    reading = args[0] == 'read'
    words = [] if reading else args[1:]
    if any(w not in ('go', 'nobackup', 'force') for w in words) or (words and words[0] != 'go'):
        sys.exit(USAGE)
    go, nobackup, force = 'go' in words, 'nobackup' in words, 'force' in words
    if not reading:
        img = open(args[0], 'rb').read()
        if len(img) != FLASH:
            sys.exit('%s is %d bytes; a TS-H492C image is %d bytes' % (args[0], len(img), FLASH))

    try:
        fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK | (os.O_EXCL if go else 0))
    except OSError as e:
        if e.errno == errno.EBUSY:
            sys.exit('%s is in use by another program; not flashing a drive that is being used' % dev)
        sys.exit('cannot open %s: %s' % (dev, e.strerror))
    ident = inquiry(fd)
    print('drive: %s' % (' '.join(ident) if ident else 'no INQUIRY answer'), flush=True)
    if not ident or ident[:2] != (VENDOR, PRODUCT):
        sys.exit('not a %s %s. Other suffixes (TS-H492A, ...) are different drives; refusing.' % (VENDOR, PRODUCT))

    if reading:
        fw = read_flash(fd, 'reading flash')
        if check_image(fw):
            sys.exit('the data read is not TS-H492C firmware (%s). Nothing saved.' % '; '.join(check_image(fw)))
        open(args[1], 'wb').write(fw)
        print('saved to %s (sha256 %s)' % (args[1], hashlib.sha256(fw).hexdigest()))
        return

    sha = hashlib.sha256(img).hexdigest()
    why = check_image(img)
    if sha not in KNOWN:
        why.append('sha256 %s is not a known release' % sha)
    print('image: %s, revision %s, %s' % (args[0], img[0x7FFE8:0x7FFEC].decode('latin1'), KNOWN.get(sha, 'unknown')))
    for w in why:
        print('  image check:', w)
    if not go:
        fw = read_flash(fd, 'reading flash')
        print('%d bytes differ' % sum(1 for x, y in zip(fw, img) if x != y))
        print('DRY-RUN: nothing written' + ('; this image would be REFUSED without force' if why else ''))
        return
    if why and not force:
        sys.exit("REFUSING: see 'image check' above. 'force' overrides (e.g. for your own backup).")

    if not nobackup:
        fw = read_flash(fd, 'reading flash')
        if fw == img:
            print('the drive already has this firmware; nothing to do')
            return
        backup = 'h492cflash-backup-%s.bin' % time.strftime('%Y%m%d-%H%M%S')
        open(backup, 'wb').write(fw)
        print('current flash saved to', backup, flush=True)

    print('== FLASHING', args[0], '==', flush=True)
    held = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT, signal.SIGTSTP}
    signal.pthread_sigmask(signal.SIG_BLOCK, held)
    try:
        plan = write_plan(img)
        for i, (name, cdb, data) in enumerate(plan):
            ok, _, desc = scsi(fd, cdb, TO_DEV if data else NONE, out=data, timeout_ms=15000)
            if ok:
                print('  %s ok' % name, flush=True)
            elif name == 'setup' or i == len(plan) - 1:
                # setup is rejected by this drive; the last block resets the drive before its status
                print('  %s: %s (expected)' % (name, desc), flush=True)
            else:
                sys.exit('%s failed: %s\nDO NOT POWER-CYCLE THE DRIVE. Run the same command again.' % (name, desc))
    finally:
        os.close(fd)
        signal.pthread_sigmask(signal.SIG_UNBLOCK, held)

    print('waiting for the drive to restart...', flush=True)
    time.sleep(20)
    fd = wait_ready(dev)
    if fd is None:
        sys.exit('the drive did not come back. DO NOT POWER-CYCLE IT; check dmesg, then run the dry run.')
    rb = read_flash(fd, 'reading back')
    n = sum(1 for x, y in zip(rb, img) if x != y)
    if n:
        sys.exit('VERIFY FAILED: %d bytes differ. DO NOT POWER-CYCLE THE DRIVE. Run the same command again.' % n)
    print('verify ok: 0 bytes differ. Drive reports %s. Reboot before dumping.' % ' '.join(inquiry(fd) or ('?',)))


if __name__ == '__main__':
    main()
