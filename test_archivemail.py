#!/usr/bin/env python
############################################################################
# Copyright (C) 2002  Paul Rodger <paul@paulrodger.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
############################################################################
"""
Test archivemail works correctly using 'pyunit'.
"""

import fcntl
import filecmp
import os
import shutil
import stat
import tempfile
import time
import unittest

import archivemail

__version__ = """$Id$"""

############ Mbox Class testing ##############

class TestMboxIsEmpty(unittest.TestCase):
    def setUp(self):
        self.empty_name = make_mbox(messages=0)
        self.not_empty_name = make_mbox(messages=1)

    def testEmpty(self):
        mbox = archivemail.Mbox(self.empty_name)
        assert(mbox.is_empty())

    def testNotEmpty(self):
        mbox = archivemail.Mbox(self.not_empty_name)
        assert(not mbox.is_empty())

    def tearDown(self):
        if os.path.exists(self.empty_name):
            os.remove(self.empty_name)
        if os.path.exists(self.not_empty_name):
            os.remove(self.not_empty_name)


class TestMboxLeaveEmpty(unittest.TestCase):
    def setUp(self):
        self.mbox_name = make_mbox()
        self.mbox_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.mbox = archivemail.Mbox(self.mbox_name)

    def testLeaveEmpty(self):
        self.mbox.leave_empty()
        assert(os.path.isfile(self.mbox_name))
        self.assertEqual(os.path.getsize(self.mbox_name), 0)
        new_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.assertEqual(new_mode, self.mbox_mode)

    def tearDown(self):
        if os.path.exists(self.mbox_name):
            os.remove(self.mbox_name)


class TestMboxProcmailLock(unittest.TestCase):
    def setUp(self):
        self.mbox_name = make_mbox()
        self.mbox_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.mbox = archivemail.Mbox(self.mbox_name)

    def testProcmailLock(self):
        lock = self.mbox_name + ".lock"
        self.mbox.procmail_lock()
        assert(os.path.isfile(lock))
        assert(is_world_readable(lock))
        self.mbox.procmail_unlock()
        assert(not os.path.isfile(lock))

    # TODO: add a test where the lock already exists

    def tearDown(self):
        if os.path.exists(self.mbox_name):
            os.remove(self.mbox_name)


class TestMboxRemove(unittest.TestCase):
    def setUp(self):
        self.mbox_name = make_mbox()
        self.mbox = archivemail.Mbox(self.mbox_name)

    def testProcmailLock(self):
        assert(os.path.exists(self.mbox_name))
        self.mbox.remove()
        assert(not os.path.exists(self.mbox_name))

    def tearDown(self):
        if os.path.exists(self.mbox_name):
            os.remove(self.mbox_name)


class TestMboxExclusiveLock(unittest.TestCase):
    def setUp(self):
        self.mbox_name = make_mbox()
        self.mbox = archivemail.Mbox(self.mbox_name)

    def testExclusiveLock(self):
        self.mbox.exclusive_lock()
        file = open(self.mbox_name, "r+")
        lock_nb = fcntl.LOCK_EX | fcntl.LOCK_NB
        self.assertRaises(IOError, fcntl.flock, file, lock_nb)

        self.mbox.exclusive_unlock()
        fcntl.flock(file, lock_nb)
        fcntl.flock(file, fcntl.LOCK_UN)

    def tearDown(self):
        if os.path.exists(self.mbox_name):
            os.remove(self.mbox_name)


class TestMboxNext(unittest.TestCase):
    def setUp(self):
        self.not_empty_name = make_mbox(messages=18)
        self.empty_name = make_mbox(messages=0)

    def testNextEmpty(self):
        mbox = archivemail.Mbox(self.empty_name)
        msg = mbox.next()
        self.assertEqual(msg, None)

    def testNextNotEmpty(self):
        mbox = archivemail.Mbox(self.not_empty_name)
        for count in range(18):
            msg = mbox.next()
            assert(msg)
        msg = mbox.next()
        self.assertEqual(msg, None)

    def tearDown(self):
        if os.path.exists(self.not_empty_name):
            os.remove(self.not_empty_name)
        if os.path.exists(self.empty_name):
            os.remove(self.empty_name)


class TestMboxWrite(unittest.TestCase):
    def setUp(self):
        self.mbox_read = make_mbox(messages=3)
        self.mbox_write = make_mbox(messages=0)

    def testWrite(self):
        read = archivemail.Mbox(self.mbox_read)
        write = archivemail.Mbox(self.mbox_write, mode="w")
        for count in range(3):
            msg = read.next()
            write.write(msg)
        read.close()
        write.close()
        assert(filecmp.cmp(self.mbox_read, self.mbox_write))

    def testWriteNone(self):
        write = archivemail.Mbox(self.mbox_write, mode="w")
        self.assertRaises(AssertionError, write.write, None)

    def tearDown(self):
        if os.path.exists(self.mbox_write):
            os.remove(self.mbox_write)
        if os.path.exists(self.mbox_read):
            os.remove(self.mbox_read)


########## generic routine testing #################


class TestIsTooOld(unittest.TestCase):
    def testOld(self):
        time_msg = time.time() - (15 * 24 * 60 * 60) # 15 days old
        assert(archivemail.is_too_old(time_message=time_msg, max_days=14))

    def testJustOld(self):
        time_msg = time.time() - (25 * 60 * 60) # 25 hours old
        assert(archivemail.is_too_old(time_message=time_msg, max_days=1))

    def testNotOld(self):
        time_msg = time.time() - (8 * 24 * 60 * 60) # 8 days old
        assert(not archivemail.is_too_old(time_message=time_msg, max_days=9))

    def testJustNotOld(self):
        time_msg = time.time() - (23 * 60 * 60) # 23 hours old
        assert(not archivemail.is_too_old(time_message=time_msg, max_days=1))

    def testFuture(self):
        time_msg = time.time() + (1 * 24 * 60 * 60) # tomorrow
        assert(not archivemail.is_too_old(time_message=time_msg, max_days=1))


class TestChooseTempDir(unittest.TestCase):
    def setUp(self):
        self.output_dir = tempfile.mktemp()
        os.mkdir(self.output_dir)
        self.sub_dir = tempfile.mktemp()
        os.mkdir(self.sub_dir)

    def testCurrentDir(self):
        archivemail._options.output_dir = None
        dir = archivemail.choose_temp_dir("dummy")
        self.assertEqual(dir, os.curdir)

    def testSubDir(self):
        archivemail._options.output_dir = None
        dir = archivemail.choose_temp_dir(os.path.join(self.sub_dir, "dummy"))
        self.assertEqual(dir, self.sub_dir)

    def testOutputDir(self):
        archivemail._options.output_dir = self.output_dir
        dir = archivemail.choose_temp_dir("dummy")
        self.assertEqual(dir, self.output_dir)

    def testSubDirOutputDir(self):
        archivemail._options.output_dir = self.output_dir
        dir = archivemail.choose_temp_dir(os.path.join(self.sub_dir, "dummy"))
        self.assertEqual(dir, self.output_dir)

    def tearDown(self):
        os.rmdir(self.output_dir)
        os.rmdir(self.sub_dir)


########## proper archival testing ###########

class TestArchiveMboxTimestampNew(unittest.TestCase):
    def setUp(self):
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 179))
        self.mtime = os.path.getmtime(self.mbox_name) - 66
        self.atime = os.path.getatime(self.mbox_name) - 88
        os.utime(self.mbox_name, (self.atime, self.mtime))
        archivemail._options.quiet = 1

    def testTime(self):
        archivemail._options.compressor = "gzip"
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        new_atime = os.path.getatime(self.mbox_name)
        new_mtime = os.path.getmtime(self.mbox_name)
        self.assertEqual(self.mtime, new_mtime)
        self.assertEqual(self.atime, new_atime)

    def tearDown(self):
        if os.path.exists(self.mbox_name):
            os.remove(self.mbox_name)
        archivemail._options.quiet = 0


class TestArchiveMboxTimestampOld(unittest.TestCase):
    def setUp(self):
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181))
        self.mtime = os.path.getmtime(self.mbox_name) - 66
        self.atime = os.path.getatime(self.mbox_name) - 88
        os.utime(self.mbox_name, (self.atime, self.mtime))
        archivemail._options.quiet = 1

    def testTime(self):
        archivemail._options.compressor = "gzip"
        archive_name = self.mbox_name + "_archive.gz"
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        new_atime = os.path.getatime(self.mbox_name)
        new_mtime = os.path.getmtime(self.mbox_name)
        self.assertEqual(self.mtime, new_mtime)
        self.assertEqual(self.atime, new_atime)

    def tearDown(self):
        if os.path.exists(self.mbox_name):
            os.remove(self.mbox_name)
        for ext in (".gz", ".bz2", ".Z"):
            if os.path.exists(self.mbox_name + ext):
                os.remove(self.mbox_name + ext)
        archivemail._options.quiet = 0


class TestArchiveMboxOld(unittest.TestCase):
    def setUp(self):
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181))
        self.mbox_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.copy_name = tempfile.mktemp()
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail._options.quiet = 1

    def testArchiveOldGzip(self):
        archivemail._options.compressor = "gzip"
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        self.assertEqual(os.path.getsize(self.mbox_name), 0)
        new_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.assertEqual(self.mbox_mode, new_mode)

        archive_name = self.mbox_name + "_archive.gz"
        assert(os.path.exists(archive_name))
        os.system("gzip -d " + archive_name)

        archive_name = self.mbox_name + "_archive"
        assert(os.path.exists(archive_name))
        assert(filecmp.cmp(archive_name, self.copy_name))
        self.tearDown()
        self.setUp()

    def testArchiveOldBzip2(self):
        archivemail._options.compressor = "bzip2"
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        self.assertEqual(os.path.getsize(self.mbox_name), 0)
        new_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.assertEqual(self.mbox_mode, new_mode)

        archive_name = self.mbox_name + "_archive.bz2"
        assert(os.path.exists(archive_name))
        os.system("bzip2 -d " + archive_name)

        archive_name = self.mbox_name + "_archive"
        assert(os.path.exists(archive_name))
        assert(filecmp.cmp(archive_name, self.copy_name))
        self.tearDown()
        self.setUp()

    def testArchiveOldCompress(self):
        archivemail._options.compressor = "compress"
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        self.assertEqual(os.path.getsize(self.mbox_name), 0)
        new_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.assertEqual(self.mbox_mode, new_mode)

        archive_name = self.mbox_name + "_archive.Z"
        assert(os.path.exists(archive_name))
        os.system("compress -d " + archive_name)

        archive_name = self.mbox_name + "_archive"
        assert(os.path.exists(archive_name))
        assert(filecmp.cmp(archive_name, self.copy_name))
        self.tearDown()
        self.setUp()

    def tearDown(self):
        if os.path.exists(self.mbox_name):
            os.remove(self.mbox_name)
        for ext in (".gz", ".bz2", ".Z"):
            if os.path.exists(self.mbox_name + ext):
                os.remove(self.mbox_name + ext)
        if os.path.exists(self.copy_name):
            os.remove(self.copy_name)
        archivemail._options.quiet = 0


class TestArchiveMboxNew(unittest.TestCase):
    def setUp(self):
        archivemail._options.quiet = 1
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 179))
        self.mbox_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.copy_name = tempfile.mktemp()
        shutil.copyfile(self.mbox_name, self.copy_name)

    def testArchiveNew(self):
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        assert(filecmp.cmp(self.mbox_name, self.copy_name))
        new_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.assertEqual(self.mbox_mode, new_mode)
        
        archive_name = self.mbox_name + "_archive.gz"
        assert(not os.path.exists(archive_name))

    def tearDown(self):
        archivemail._options.quiet = 0
        if os.path.exists(self.mbox_name):
            os.remove(self.mbox_name)
        if os.path.exists(self.copy_name):
            os.remove(self.copy_name)


########## helper routines ############

def make_message(hours_old=0):
    time_message = time.time() - (60 * 60 * hours_old)
    time_string = time.asctime(time.localtime(time_message))

    return """From sender@domain %s
From: sender@domain
To: receipient@domain
Subject: This is a dummy message
Date: %s

This is the message body.
It's very exciting.


""" % (time_string, time_string)

def make_mbox(messages=1, hours_old=0):
    name = tempfile.mktemp()
    file = open(name, "w")
    for count in range(messages):
        file.write(make_message(hours_old=hours_old))
    file.close()
    return name
    
def is_world_readable(path):
    """Return true if the path is world-readable, false otherwise"""
    assert(path)
    return (os.stat(path)[stat.ST_MODE] & stat.S_IROTH)


if __name__ == "__main__":
    unittest.main()
