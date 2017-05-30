#!/usr/bin/python3
# -*- coding: utf-8; tab-width: 4; indent-tabs-mode: t -*-

import os
import sys
import errno
import shutil
import ctypes
import subprocess


class _UtilNewMountNamespace:

    _CLONE_NEWNS = 0x00020000               # <linux/sched.h>
    _MS_REC = 16384                         # <sys/mount.h>
    _MS_PRIVATE = 1 << 18                   # <sys/mount.h>
    _libc = None
    _mount = None
    _setns = None
    _unshare = None

    def __init__(self):
        if self._libc is None:
            self._libc = ctypes.CDLL('libc.so.6', use_errno=True)
            self._mount = self._libc.mount
            self._mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_ulong, ctypes.c_char_p]
            self._mount.restype = ctypes.c_int
            self._setns = self._libc.setns
            self._unshare = self._libc.unshare

        self.parentfd = None

    def __enter__(self):
        self.parentfd = open("/proc/%d/ns/mnt" % (os.getpid()), 'r')

        # copied from unshare.c of util-linux
        try:
            if self._unshare(self._CLONE_NEWNS) != 0:
                e = ctypes.get_errno()
                raise OSError(e, errno.errorcode[e])

            srcdir = ctypes.c_char_p("none".encode("utf_8"))
            target = ctypes.c_char_p("/".encode("utf_8"))
            if self._mount(srcdir, target, None, (self._MS_REC | self._MS_PRIVATE), None) != 0:
                e = ctypes.get_errno()
                raise OSError(e, errno.errorcode[e])
        except BaseException:
            self.parentfd.close()
            self.parentfd = None
            raise

    def __exit__(self, *_):
        self._setns(self.parentfd.fileno(), 0)
        self.parentfd.close()
        self.parentfd = None


assert len(sys.argv) == 6
tmpDir = sys.argv[1]
ownResolvConf = sys.argv[2]
interface = sys.argv[3]
username = sys.argv[4]
password = sys.argv[5]

tmpEtcPppDir = os.path.join(tmpDir, "etc-ppp")
tmpPapSecretsFile = os.path.join(tmpEtcPppDir, "pap-secrets")
tmpIpUpScript = os.path.join(tmpEtcPppDir, "ip-up")
tmpIpDownScript = os.path.join(tmpEtcPppDir, "ip-down")
tmpPeerFile = os.path.join(tmpEtcPppDir, "peers", "wan")
proc = None

try:
    os.mkdir(tmpEtcPppDir)

    if username != "" and password != "":
        with open(tmpPapSecretsFile, "w") as f:
            buf = ""
            buf += "%s wan \"%s\" *\n" % (username, password)
            f.write(buf)
        os.chmod(tmpPapSecretsFile, 0o600)

    with open(tmpIpUpScript, "w") as f:
        buf = ""
        buf += "#!/bin/sh\n"
        buf += "\n"
        buf += "echo \"# Generated by wrtd\" > %s\n" % (ownResolvConf)
        buf += "[ -n \"$DNS1\" ] && echo \"nameserver $DNS1\" >> %s\n" % (ownResolvConf)
        buf += "[ -n \"$DNS2\" ] && echo \"nameserver $DNS2\" >> %s\n" % (ownResolvConf)
        f.write(buf)
    os.chmod(tmpIpUpScript, 0o755)

    with open(tmpIpDownScript, "w") as f:
        buf = ""
        buf += "#!/bin/sh\n"
        buf += "\n"
        buf += "echo \"\" > %s\n" % (ownResolvConf)
    os.chmod(tmpIpDownScript, 0o755)

    os.mkdir(os.path.dirname(tmpPeerFile))
    with open(tmpPeerFile, "w") as f:
        # buf = optionTemplate.replace("$USERNAME", username)
        buf = ""
        buf += "\n"
        buf += "pty \"pppoe -I %s\"\n" % (interface)
        buf += "lock\n"
        buf += "noauth\n"
        buf += "ifname wrt-ppp-wan\n"
        buf += "persist\n"
        buf += "holdoff 10\n"
        buf += "defaultroute\n"
        buf += "usepeerdns\n"
        buf += "remotename wan\n"
        if username != "":
            buf += "user %s\n" % (username)
        f.write(buf)

    with _UtilNewMountNamespace():
        # pppd read config files from the fixed location /etc/ppp
        # this behavior is bad so we use mount namespace to workaround it
        subprocess.check_call(["/bin/mount", "--bind", tmpEtcPppDir, "/etc/ppp"])
        cmd = "/usr/sbin/pppd call wan nodetach"
        proc = subprocess.Popen(cmd, shell=True, universal_newlines=True)
        proc.wait()
finally:
    if os.path.exists(tmpEtcPppDir):
        shutil.rmtree(tmpEtcPppDir)
    if proc is not None:
        sys.exit(proc.returncode)
