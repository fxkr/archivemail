#! /usr/bin/env python
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
# $Id$
"""
Unit-test archivemail using 'PyUnit'.

TODO: add tests for:
    * procmail locks already existing
    * messages with corrupted date headers
    * archiving maildir-format mailboxes
    * archiving MH-format mailboxes
    * more tests running archivemail via os.system()
    * preservation of status information from maildir to mbox
    * a 3rd party process changing the mbox file being read

"""

import sys

def check_python_version(): 
    """Abort if we are running on python < v2.1"""
    too_old_error = """This test script requires python version 2.1 or later.
This is because it requires the pyUnit 'unittest' module, which only got
released in python version 2.1. You should still be able to run archivemail on
python versions 2.0 and above, however -- just not test it.
Your version of python is: %s""" % sys.version
    try: 
        version = sys.version_info  # we might not even have this function! :)
        if (version[0] < 2) or ((version[0] == 2) and (version[1] < 1)):
            print too_old_error
            sys.exit(1)
    except AttributeError:
        print too_old_error
        sys.exit(1)

check_python_version()  # define & run this early because 'unittest' is new

import copy
import fcntl
import filecmp
import os
import re
import shutil
import stat
import tempfile
import time
import unittest

try:
    import archivemail
except ImportError:
    print "The archivemail script needs to be called 'archivemail.py'"
    print "and should be in the current directory in order to be imported"
    print "and tested. Sorry."
    if os.path.isfile("archivemail"):
        print "Try renaming it from 'archivemail' to 'archivemail.py'."
    sys.exit(1)



############ Mbox Class testing ##############

class TestMboxIsEmpty(unittest.TestCase):
    def setUp(self):
        self.empty_name = make_mbox(messages=0)
        self.not_empty_name = make_mbox(messages=1)

    def testEmpty(self):
        """is_empty() should be true for an empty mbox"""
        mbox = archivemail.Mbox(self.empty_name)
        assert(mbox.is_empty())

    def testNotEmpty(self):
        """is_empty() should be false for a non-empty mbox"""
        mbox = archivemail.Mbox(self.not_empty_name)
        assert(not mbox.is_empty())

    def tearDown(self):
        for name in (self.empty_name, self.not_empty_name):
            if os.path.exists(name):
                os.remove(name)


class TestMboxLeaveEmpty(unittest.TestCase):
    def setUp(self):
        self.mbox_name = make_mbox()
        self.mbox_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.mbox = archivemail.Mbox(self.mbox_name)

    def testLeaveEmpty(self):
        """leave_empty should leave a zero-length file"""
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
        """procmail_lock/unlock should create/delete a lockfile"""
        lock = self.mbox_name + ".lock"
        self.mbox.procmail_lock()
        assert(os.path.isfile(lock))
        assert(is_world_readable(lock))
        self.mbox.procmail_unlock()
        assert(not os.path.isfile(lock))

    def tearDown(self):
        if os.path.exists(self.mbox_name):
            os.remove(self.mbox_name)


class TestMboxRemove(unittest.TestCase):
    def setUp(self):
        self.mbox_name = make_mbox()
        self.mbox = archivemail.Mbox(self.mbox_name)

    def testMboxRemove(self):
        """remove() should delete a mbox mailbox"""
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
        """exclusive_lock/unlock should create/delete an advisory lock"""
        self.mbox.exclusive_lock()
        file = open(self.mbox_name, "r+")
        lock_nb = fcntl.LOCK_EX | fcntl.LOCK_NB
        self.assertRaises(IOError, fcntl.flock, file.fileno(), lock_nb)

        self.mbox.exclusive_unlock()
        fcntl.flock(file.fileno(), lock_nb)
        fcntl.flock(file.fileno(), fcntl.LOCK_UN)

    def tearDown(self):
        if os.path.exists(self.mbox_name):
            os.remove(self.mbox_name)


class TestMboxNext(unittest.TestCase):
    def setUp(self):
        self.not_empty_name = make_mbox(messages=18)
        self.empty_name = make_mbox(messages=0)

    def testNextEmpty(self):
        """mbox.next() should return None on an empty mailbox"""
        mbox = archivemail.Mbox(self.empty_name)
        msg = mbox.next()
        self.assertEqual(msg, None)

    def testNextNotEmpty(self):
        """mbox.next() should a message on a populated mailbox"""
        mbox = archivemail.Mbox(self.not_empty_name)
        for count in range(18):
            msg = mbox.next()
            assert(msg)
        msg = mbox.next()
        self.assertEqual(msg, None)

    def tearDown(self):
        for name in (self.not_empty_name, self.empty_name):
            if os.path.exists(name):
                os.remove(name)


class TestMboxWrite(unittest.TestCase):
    def setUp(self):
        self.mbox_read = make_mbox(messages=3)
        self.mbox_write = make_mbox(messages=0)

    def testWrite(self):
        """mbox.write() should append messages to a mbox mailbox"""
        read = archivemail.Mbox(self.mbox_read)
        write = archivemail.Mbox(self.mbox_write, mode="w")
        for count in range(3):
            msg = read.next()
            write.write(msg)
        read.close()
        write.close()
        assert(filecmp.cmp(self.mbox_read, self.mbox_write, shallow=0))

    def testWriteNone(self):
        """calling mbox.write() with no message should raise AssertionError"""
        read = archivemail.Mbox(self.mbox_read)
        write = archivemail.Mbox(self.mbox_write, mode="w")
        self.assertRaises(AssertionError, write.write, None)

    def tearDown(self):
        for name in (self.mbox_write, self.mbox_read):
            if os.path.exists(name):
                os.remove(name)

########## options class testing #################

class TestOptionDefaults(unittest.TestCase):
    def testVerbose(self):
        """verbose should be off by default"""
        self.assertEqual(archivemail.options.verbose, 0)

    def testDaysOldMax(self):
        """default archival time should be 180 days"""
        self.assertEqual(archivemail.options.days_old_max, 180)

    def testQuiet(self):
        """quiet should be off by default"""
        self.assertEqual(archivemail.options.quiet, 0)

    def testDeleteOldMail(self):
        """we should not delete old mail by default"""
        self.assertEqual(archivemail.options.quiet, 0)

    def testNoCompress(self):
        """no-compression should be off by default"""
        self.assertEqual(archivemail.options.no_compress, 0)

    def testIncludeFlagged(self):
        """we should not archive flagged messages by default"""
        self.assertEqual(archivemail.options.include_flagged, 0)

    def testPreserveUnread(self):
        """we should not preserve unread messages by default"""
        self.assertEqual(archivemail.options.preserve_unread, 0)

########## archivemail.is_older_than_days() unit testing #################

class TestIsTooOld(unittest.TestCase):
    def testVeryOld(self):
        """with max_days=360, should be true for these dates > 1 year"""
        for years in range(1, 10):
            time_msg = time.time() - (years * 365 * 24 * 60 * 60)
            assert(archivemail.is_older_than_days(time_message=time_msg,
                max_days=360))

    def testOld(self):
        """with max_days=14, should be true for these dates > 14 days"""
        for days in range(14, 360):
            time_msg = time.time() - (days * 24 * 60 * 60)
            assert(archivemail.is_older_than_days(time_message=time_msg, 
                max_days=14))

    def testJustOld(self):
        """with max_days=1, should be true for these dates >= 1 day"""
        for minutes in range(0, 61):
            time_msg = time.time() - (25 * 60 * 60) + (minutes * 60)
            assert(archivemail.is_older_than_days(time_message=time_msg, 
                max_days=1))

    def testNotOld(self):
        """with max_days=9, should be false for these dates < 9 days"""
        for days in range(0, 9):
            time_msg = time.time() - (days * 24 * 60 * 60)
            assert(not archivemail.is_older_than_days(time_message=time_msg, 
                max_days=9))

    def testJustNotOld(self):
        """with max_days=1, should be false for these hours <= 1 day"""
        for minutes in range(0, 60):
            time_msg = time.time() - (23 * 60 * 60) - (minutes * 60)
            assert(not archivemail.is_older_than_days(time_message=time_msg, 
                max_days=1))

    def testFuture(self):
        """with max_days=1, should be false for times in the future"""
        for minutes in range(0, 60):
            time_msg = time.time() + (minutes * 60)
            assert(not archivemail.is_older_than_days(time_message=time_msg, 
                max_days=1))

################ archivemail.choose_temp_dir() unit testing #############

class TestChooseTempDir(unittest.TestCase):
    def setUp(self):
        self.output_dir = tempfile.mktemp()
        os.mkdir(self.output_dir)
        self.sub_dir = tempfile.mktemp()
        os.mkdir(self.sub_dir)

    def testCurrentDir(self):
        """use the current directory as a temp directory with no output dir"""
        archivemail.options.output_dir = None
        dir = archivemail.choose_temp_dir("dummy")
        self.assertEqual(dir, os.curdir)

    def testSubDir(self):
        """use the mailbox parent directory as a temp directory"""
        archivemail.options.output_dir = None
        dir = archivemail.choose_temp_dir(os.path.join(self.sub_dir, "dummy"))
        self.assertEqual(dir, self.sub_dir)

    def testOutputDir(self):
        """use the output dir as a temp directory when specified"""
        archivemail.options.output_dir = self.output_dir
        dir = archivemail.choose_temp_dir("dummy")
        self.assertEqual(dir, self.output_dir)

    def testSubDirOutputDir(self):
        """use the output dir as temp when given a mailbox directory"""
        archivemail.options.output_dir = self.output_dir
        dir = archivemail.choose_temp_dir(os.path.join(self.sub_dir, "dummy"))
        self.assertEqual(dir, self.output_dir)

    def tearDown(self):
        os.rmdir(self.output_dir)
        os.rmdir(self.sub_dir)


########## acceptance testing ###########

class TestArchiveMbox(unittest.TestCase):
    """archiving should work based on the date of messages given"""
    old_mbox = None
    new_mbox = None
    mixed_mbox = None
    copy_name = None
    mbox_name = None

    def setUp(self):
        archivemail.options.quiet = 1

    def testOld(self):
        """archiving an old mailbox"""
        for execute in ("package", "system"):
            self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181))
            self.mbox_mode = os.stat(self.mbox_name)[stat.ST_MODE]
            self.copy_name = tempfile.mktemp()
            shutil.copyfile(self.mbox_name, self.copy_name)
            if execute == "package":
                archivemail.options.quiet = 1
                archivemail.archive(self.mbox_name)
            elif execute == "system":
                run = "./archivemail.py --quiet %s" % self.mbox_name
                self.assertEqual(os.system(run), 0)
            else:
                sys.exit(1)
            assert(os.path.exists(self.mbox_name))
            self.assertEqual(os.path.getsize(self.mbox_name), 0)
            new_mode = os.stat(self.mbox_name)[stat.ST_MODE]
            self.assertEqual(self.mbox_mode, new_mode)
            archive_name = self.mbox_name + "_archive.gz"
            assert(os.path.exists(archive_name))
            self.assertEqual(os.system("gzip -d %s" % archive_name), 0)
            archive_name = self.mbox_name + "_archive"
            assert(os.path.exists(archive_name))
            assert(filecmp.cmp(archive_name, self.copy_name, shallow=0))
            self.tearDown()

    def testOldFromInBody(self):
        """archiving an old mailbox with 'From ' in the body"""
        body = """This is a message with ^From at the start of a line
From is on this line
This is after the ^From line"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181), body=body)
        self.copy_name = tempfile.mktemp()
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        self.assertEqual(os.path.getsize(self.mbox_name), 0)
        archive_name = self.mbox_name + "_archive.gz"
        assert(os.path.exists(archive_name))
        self.assertEqual(os.system("gzip -d %s" % archive_name), 0)
        archive_name = self.mbox_name + "_archive"
        assert(os.path.exists(archive_name))
        assert(filecmp.cmp(archive_name, self.copy_name, shallow=0))

    def testDateSystem(self):
        """test that the --date option works as expected"""
        test_headers = (
            {
                'From_' : 'sender@dummy.domain Fri Jul 28 16:11:36 2030',
                'Date' : 'Fri, 28 Jul 2000 16:11:36 +1000',
            },
            {
                'From_' : 'sender@dummy.domain Fri Jul 28 16:11:36 2000',
                'Date' : None,
            },
            {
                'From_' : 'sender@dummy.domain Fri Jul 28 16:11:36 2030',
                'Date' : None,
                'Delivery-date' : 'Fri, 28 Jul 2000 16:11:36 +1000',
            },
            {
                'From_' : 'sender@dummy.domain Fri Jul 28 16:11:36 2030',
                'Date' : None,
                'Resent-Date' : 'Fri, 28 Jul 2000 16:11:36 +1000',
            },
        )
        for headers in test_headers:
            for option in ('--date=2000-07-29', '-D2000-07-29', 
                '--date="29 Jul 2000"', '--date="29 July 2000"'):
                self.mbox_name = make_mbox(messages=3, headers=headers)
                self.copy_name = tempfile.mktemp()
                shutil.copyfile(self.mbox_name, self.copy_name)
                run = "./archivemail.py -q %s %s" % (option, self.mbox_name)
                self.assertEqual(os.system(run), 0)
                assert(os.path.exists(self.mbox_name))
                self.assertEqual(os.path.getsize(self.mbox_name), 0)
                archive_name = self.mbox_name + "_archive.gz"
                assert(os.path.exists(archive_name))
                self.assertEqual(os.system("gzip -d %s" % archive_name), 0)
                archive_name = self.mbox_name + "_archive"
                assert(os.path.exists(archive_name))
                assert(filecmp.cmp(archive_name, self.copy_name, shallow=0))
                self.tearDown()
            for option in ('--date=2000-07-27', '-D2000-07-27', 
                '--date="27 Jul 2000"', '--date="27 July 2000"'):
                self.mbox_name = make_mbox(messages=3, headers=headers)
                self.copy_name = tempfile.mktemp()
                shutil.copyfile(self.mbox_name, self.copy_name)
                run = "./archivemail.py -q %s %s" % (option, self.mbox_name)
                self.assertEqual(os.system(run), 0)
                assert(os.path.exists(self.mbox_name))
                assert(filecmp.cmp(self.mbox_name, self.copy_name, shallow=0))
                archive_name = self.mbox_name + "_archive.gz"
                assert(not os.path.exists(archive_name))
                self.tearDown()

    def testMixed(self):
        """archiving a mixed mailbox"""
        for execute in ("package", "system"):
            self.new_mbox = make_mbox(messages=3, hours_old=(24 * 179))
            self.old_mbox = make_mbox(messages=3, hours_old=(24 * 181))
            self.mbox_name = tempfile.mktemp()
            shutil.copyfile(self.new_mbox, self.mbox_name)
            append_file(self.old_mbox, self.mbox_name)
            if execute == "package":
                archivemail.options.quiet = 1
                archivemail.archive(self.mbox_name)
            elif execute == "system":
                run = "./archivemail.py --quiet %s" % self.mbox_name
                self.assertEqual(os.system(run), 0)
            else:
                sys.exit(1)
            assert(os.path.exists(self.mbox_name))
            assert(filecmp.cmp(self.new_mbox, self.mbox_name, shallow=0))
            archive_name = self.mbox_name + "_archive.gz"
            assert(os.path.exists(archive_name))
            self.assertEqual(os.system("gzip -d %s" % archive_name), 0)
            archive_name = self.mbox_name + "_archive"
            assert(os.path.exists(archive_name))
            assert(filecmp.cmp(archive_name, self.old_mbox, shallow=0))
            self.tearDown()

    def testNew(self):
        """archiving a new mailbox""" 
        for execute in ("package", "system"):
            self.mbox_name = make_mbox(messages=3, hours_old=(24 * 179))
            self.mbox_mode = os.stat(self.mbox_name)[stat.ST_MODE]
            self.copy_name = tempfile.mktemp()
            shutil.copyfile(self.mbox_name, self.copy_name)
            if execute == "package":
                archivemail.options.quiet = 1
                archivemail.archive(self.mbox_name)
            elif execute == "system":
                run = "./archivemail.py --quiet %s" % self.mbox_name
                self.assertEqual(os.system(run), 0)
            else:
                sys.exit(1)
            assert(os.path.exists(self.mbox_name))
            assert(filecmp.cmp(self.mbox_name, self.copy_name, shallow=0))
            new_mode = os.stat(self.mbox_name)[stat.ST_MODE]
            self.assertEqual(self.mbox_mode, new_mode)
            archive_name = self.mbox_name + "_archive.gz"
            assert(not os.path.exists(archive_name))
            self.tearDown()


    def testOldExisting(self):
        """archiving an old mailbox with an existing archive"""
        for execute in ("package", "system"):
            self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181))
            self.mbox_mode = os.stat(self.mbox_name)[stat.ST_MODE]
            self.copy_name = tempfile.mktemp()
            archive_name = self.mbox_name + "_archive"
            shutil.copyfile(self.mbox_name, self.copy_name) 
            shutil.copyfile(self.mbox_name, archive_name) # archive has 3 msgs
            append_file(self.mbox_name, self.copy_name) # copy now has 6 msgs
            self.assertEqual(os.system("gzip %s" % archive_name), 0)
            if execute == "package":
                archivemail.options.quiet = 1
                archivemail.archive(self.mbox_name)
            elif execute == "system":
                run = "./archivemail.py --quiet %s" % self.mbox_name
                self.assertEqual(os.system(run), 0)
            else:
                sys.exit(1)
            assert(os.path.exists(self.mbox_name))
            self.assertEqual(os.path.getsize(self.mbox_name), 0)
            new_mode = os.stat(self.mbox_name)[stat.ST_MODE]
            self.assertEqual(self.mbox_mode, new_mode)
            archive_name = self.mbox_name + "_archive.gz"
            assert(os.path.exists(archive_name))
            self.assertEqual(os.system("gzip -d %s" % archive_name), 0)
            archive_name = self.mbox_name + "_archive"
            assert(os.path.exists(archive_name))
            assert(filecmp.cmp(archive_name, self.copy_name, shallow=0))
            self.tearDown()

    def testOldWeirdHeaders(self):
        """archiving old mailboxes with weird headers"""
        weird_headers = (
            {   # we should archive even though date < epoch
                'From_' : 'sender@dummy.domain Sat Feb 09 02:35:07 1962',
                'Date'  : 'Fri, 08 Feb 1962 07:22:54 -0500',
            },
            {   # we should archive because of the date on the 'From_' line
                'From_' : 'sender@dummy.domain Fri Jul 28 16:11:36 2000',
                'Date'  : 'Friskhdfkjkh, 28 Jul 2002 1line noise6:11:36 +1000',
            },
            {   # we should archive because of the date on the 'From_' line
                'From_' : 'sender@dummy.domain Fri Jul 28 16:11:36 2000',
                'Date'  : None,
            },
            {   # we should archive because of the date in 'Delivery-date'
                'From_' : 'sender@dummy.domain Fri Jul 28 16:11:36 2030',
                'Date'  : 'Frcorruptioni, 28 Jul 20line noise00 16:6 +1000',
                'Delivery-date' : 'Fri, 28 Jul 2000 16:11:36 +1000',
            },
            {   # we should archive because of the date in 'Delivery-date'
                'From_' : 'sender@dummy.domain Fri Jul 28 16:11:36 2030',
                'Date' : None,
                'Delivery-date' : 'Fri, 28 Jul 2000 16:11:36 +1000',
            },
            {   # we should archive because of the date in 'Resent-Date'
                'From_' : 'sender@dummy.domain Fri Jul 28 16:11:36 2030',
                'Date'  : 'Frcorruptioni, 28 Jul 20line noise00 16:6 +1000',
                'Resent-Date' : 'Fri, 28 Jul 2000 16:11:36 +1000',
            },
            {   # we should archive because of the date in 'Resent-Date'
                'From_' : 'sender@dummy.domain Fri Jul 28 16:11:36 2030',
                'Date' : None,
                'Resent-Date' : 'Fri, 28 Jul 2000 16:11:36 +1000',
            },
        )
        for headers in weird_headers:
            self.setUp()
            self.mbox_name = make_mbox(messages=3, headers=headers)
            self.copy_name = tempfile.mktemp()
            shutil.copyfile(self.mbox_name, self.copy_name)
            archivemail.archive(self.mbox_name)
            assert(os.path.exists(self.mbox_name))
            self.assertEqual(os.path.getsize(self.mbox_name), 0)
            archive_name = self.mbox_name + "_archive.gz"
            assert(os.path.exists(archive_name))
            self.assertEqual(os.system("gzip -d %s" % archive_name), 0)
            archive_name = self.mbox_name + "_archive"
            assert(os.path.exists(archive_name))
            assert(filecmp.cmp(archive_name, self.copy_name, shallow=0))
            self.tearDown()

    def tearDown(self):
        archivemail.options.quiet = 0
        archive = self.mbox_name + "_archive"
        for name in (self.mbox_name, self.old_mbox, self.new_mbox, 
            self.copy_name, archive, archive + ".gz"):
            if name and os.path.exists(name):
                os.remove(name)


class TestArchiveMboxTimestamp(unittest.TestCase):
    """original mbox timestamps should always be preserved"""
    def setUp(self):
        archivemail.options.quiet = 1

    def testNew(self):
        """mbox timestamps should not change after no archival"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 179))
        self.mtime = os.path.getmtime(self.mbox_name) - 66
        self.atime = os.path.getatime(self.mbox_name) - 88
        os.utime(self.mbox_name, (self.atime, self.mtime))
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        new_atime = os.path.getatime(self.mbox_name)
        new_mtime = os.path.getmtime(self.mbox_name)
        self.assertEqual(self.mtime, new_mtime)
        self.assertEqual(self.atime, new_atime)

    def testMixed(self):
        """mbox timestamps should not change after semi-archival"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181))
        self.mtime = os.path.getmtime(self.mbox_name) - 66
        self.atime = os.path.getatime(self.mbox_name) - 88
        os.utime(self.mbox_name, (self.atime, self.mtime))
        archive_name = self.mbox_name + "_archive.gz"
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        new_atime = os.path.getatime(self.mbox_name)
        new_mtime = os.path.getmtime(self.mbox_name)
        self.assertEqual(self.mtime, new_mtime)
        self.assertEqual(self.atime, new_atime)

    def testOld(self):
        """mbox timestamps should not change after archival"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181))
        self.mtime = os.path.getmtime(self.mbox_name) - 66
        self.atime = os.path.getatime(self.mbox_name) - 88
        os.utime(self.mbox_name, (self.atime, self.mtime))
        archive_name = self.mbox_name + "_archive.gz"
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        new_atime = os.path.getatime(self.mbox_name)
        new_mtime = os.path.getmtime(self.mbox_name)
        self.assertEqual(self.mtime, new_mtime)
        self.assertEqual(self.atime, new_atime)

    def tearDown(self):
        archivemail.options.quiet = 0
        for name in (self.mbox_name, self.mbox_name + "_archive.gz"):
            if os.path.exists(name):
                os.remove(name)


class TestArchiveMboxPreserveStatus(unittest.TestCase):
    """make sure the 'preserve_unread' option works"""
    def setUp(self):
        archivemail.options.quiet = 1
        archivemail.options.preserve_unread = 1

    def testOldRead(self):
        """archiving an old read mailbox should create an archive"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181), \
            headers={"Status":"RO"})
        self.copy_name = tempfile.mktemp()
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        self.assertEqual(os.path.getsize(self.mbox_name), 0)
        archive_name = self.mbox_name + "_archive.gz"
        assert(os.path.exists(archive_name))
        self.assertEqual(os.system("gzip -d %s" % archive_name), 0)
        archive_name = self.mbox_name + "_archive"
        assert(os.path.exists(archive_name))
        assert(filecmp.cmp(archive_name, self.copy_name, shallow=0))

    def testOldUnread(self):
        """archiving an unread mailbox should not create an archive"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181))
        self.copy_name = tempfile.mktemp()
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        assert(filecmp.cmp(self.mbox_name, self.copy_name, shallow=0))
        archive_name = self.mbox_name + "_archive.gz"
        assert(not os.path.exists(archive_name))

    def tearDown(self):
        archivemail.options.quiet = 0
        archivemail.options.preserve_unread = 0
        archive = self.mbox_name + "_archive"
        for name in (self.mbox_name, self.copy_name, archive, archive + ".gz"):
            if os.path.exists(name):
                os.remove(name)


class TestArchiveMboxSuffix(unittest.TestCase):
    """make sure the 'suffix' option works"""
    def testSuffix(self):
        """archiving with specified --suffix arguments"""
        for suffix in ("_static_", "_%B_%Y", "-%Y-%m-%d"):
            for execute in ("system_long", "system_short", "package"):
                self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181))
                self.copy_name = tempfile.mktemp()
                shutil.copyfile(self.mbox_name, self.copy_name)
                if execute == "system_long":
                    run = "./archivemail.py --quiet --suffix='%s' %s" % \
                        (suffix, self.mbox_name)
                    self.assertEqual(os.system(run), 0)
                elif execute == "system_short":
                    run = "./archivemail.py --quiet -s'%s' %s" % \
                        (suffix, self.mbox_name)
                    self.assertEqual(os.system(run), 0)
                elif execute == "package":
                    archivemail.options.archive_suffix = suffix
                    archivemail.options.quiet = 1
                    archivemail.archive(self.mbox_name)
                else:
                    sys.exit(1)
                assert(os.path.exists(self.mbox_name))
                self.assertEqual(os.path.getsize(self.mbox_name), 0)
                parsed_suffix = time.strftime(suffix, time.localtime(time.time()))
                archive_name = self.mbox_name + parsed_suffix + ".gz"
                assert(os.path.exists(archive_name))
                self.assertEqual(os.system("gzip -d %s" % archive_name), 0)
                archive_name = re.sub("\.gz$", "", archive_name)
                assert(os.path.exists(archive_name))
                assert(filecmp.cmp(archive_name, self.copy_name, shallow=0))
                os.remove(archive_name)
                self.tearDown()

    def tearDown(self):
        archivemail.options.quiet = 0
        archivemail.options.archive_suffix = "_archive"
        archive = self.mbox_name + "_archive"
        for name in (self.mbox_name, self.copy_name, archive, archive + ".gz"):
            if os.path.exists(name):
                os.remove(name)


class TestArchiveMboxFlagged(unittest.TestCase):
    """make sure the 'include_flagged' option works"""
    def setUp(self):
        archivemail.options.quiet = 1

    def testOld(self):
        """by default, old flagged messages should not be archived"""
        archivemail.options.include_flagged = 0
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181), \
            headers={"X-Status":"F"})
        self.copy_name = tempfile.mktemp()
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        assert(filecmp.cmp(self.mbox_name, self.copy_name, shallow=0))
        archive_name = self.mbox_name + "_archive.gz"
        assert(not os.path.exists(archive_name))

    def testIncludeFlaggedNew(self):
        """new flagged messages should not be archived with include_flagged"""
        archivemail.options.include_flagged = 1
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 179), \
            headers={"X-Status":"F"})
        self.copy_name = tempfile.mktemp()
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        assert(filecmp.cmp(self.mbox_name, self.copy_name, shallow=0))
        archive_name = self.mbox_name + "_archive.gz"
        assert(not os.path.exists(archive_name))

    def testIncludeFlaggedOld(self):
        """old flagged messages should be archived with include_flagged"""
        archivemail.options.include_flagged = 1
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181), \
            headers={"X-Status":"F"})
        self.copy_name = tempfile.mktemp()
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        self.assertEqual(os.path.getsize(self.mbox_name), 0)
        archive_name = self.mbox_name + "_archive.gz"
        assert(os.path.exists(archive_name))
        self.assertEqual(os.system("gzip -d %s" % archive_name), 0)
        archive_name = self.mbox_name + "_archive"
        assert(os.path.exists(archive_name))
        assert(filecmp.cmp(archive_name, self.copy_name, shallow=0))

    def tearDown(self):
        archivemail.options.include_flagged = 0
        archivemail.options.quiet = 0
        archive = self.mbox_name + "_archive"
        for name in (self.mbox_name, self.copy_name, archive, archive + ".gz"):
            if os.path.exists(name):
                os.remove(name)


class TestArchiveMboxUncompressed(unittest.TestCase):
    """make sure that the 'no_compress' option works"""
    mbox_name = None
    new_mbox = None
    old_mbox = None
    copy_name = None

    def setUp(self):
        archivemail.options.quiet = 1
        archivemail.options.no_compress = 1

    def testOld(self):
        """archiving an old mailbox uncompressed"""
        for execute in ("package", "system"):
            self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181))
            self.mbox_mode = os.stat(self.mbox_name)[stat.ST_MODE]
            self.copy_name = tempfile.mktemp()
            shutil.copyfile(self.mbox_name, self.copy_name)
            if execute == "package":
                archivemail.options.no_compress = 1
                archivemail.options.quiet = 1
                archivemail.archive(self.mbox_name)
            elif execute == "system":
                run = "./archivemail.py --no-compress --quiet %s" % \
                    self.mbox_name
                self.assertEqual(os.system(run), 0)
            else:
                sys.exit(1)
            assert(os.path.exists(self.mbox_name))
            self.assertEqual(os.path.getsize(self.mbox_name), 0)
            new_mode = os.stat(self.mbox_name)[stat.ST_MODE]
            self.assertEqual(self.mbox_mode, new_mode)
            archive_name = self.mbox_name + "_archive"
            assert(os.path.exists(archive_name))
            assert(filecmp.cmp(archive_name, self.copy_name, shallow=0))
            assert(not os.path.exists(archive_name + ".gz"))
            self.tearDown()

    def testNew(self):
        """archiving a new mailbox uncompressed"""
        for execute in ("package", "system"):
            self.mbox_name = make_mbox(messages=3, hours_old=(24 * 179))
            self.mbox_mode = os.stat(self.mbox_name)[stat.ST_MODE]
            self.copy_name = tempfile.mktemp()
            shutil.copyfile(self.mbox_name, self.copy_name)
            if execute == "package":
                archivemail.options.no_compress = 1
                archivemail.options.quiet = 1
                archivemail.archive(self.mbox_name)
            elif execute == "system":
                run = "./archivemail.py --no-compress --quiet %s" % \
                    self.mbox_name
                self.assertEqual(os.system(run), 0)
            else:
                sys.exit(1)
            assert(os.path.exists(self.mbox_name))
            assert(filecmp.cmp(self.mbox_name, self.copy_name, shallow=0))
            new_mode = os.stat(self.mbox_name)[stat.ST_MODE]
            self.assertEqual(self.mbox_mode, new_mode)
            archive_name = self.mbox_name + "_archive"
            assert(not os.path.exists(archive_name))
            assert(not os.path.exists(archive_name + ".gz"))
            self.tearDown()

    def testMixed(self):
        """archiving a mixed mailbox uncompressed"""
        for execute in ("package", "system"):
            self.new_mbox = make_mbox(messages=3, hours_old=(24 * 179))
            self.old_mbox = make_mbox(messages=3, hours_old=(24 * 181))
            self.mbox_name = tempfile.mktemp()
            shutil.copyfile(self.new_mbox, self.mbox_name)
            append_file(self.old_mbox, self.mbox_name)
            if execute == "package":
                archivemail.options.no_compress = 1
                archivemail.options.quiet = 1
                archivemail.archive(self.mbox_name)
            elif execute == "system":
                run = "./archivemail.py --no-compress --quiet %s" % \
                    self.mbox_name
                self.assertEqual(os.system(run), 0)
            else:
                sys.exit(1)
            assert(os.path.exists(self.mbox_name))
            assert(filecmp.cmp(self.new_mbox, self.mbox_name, shallow=0))
            archive_name = self.mbox_name + "_archive"
            assert(os.path.exists(archive_name))
            assert(filecmp.cmp(archive_name, self.old_mbox, shallow=0))
            assert(not os.path.exists(archive_name + ".gz"))
            self.tearDown()

    def testOldExists(self):
        """archiving an old mailbox uncopressed with an existing archive"""
        for execute in ("package", "system"):
            self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181))
            self.mbox_mode = os.stat(self.mbox_name)[stat.ST_MODE]
            self.copy_name = tempfile.mktemp()
            archive_name = self.mbox_name + "_archive"
            shutil.copyfile(self.mbox_name, self.copy_name) 
            shutil.copyfile(self.mbox_name, archive_name) # archive has 3 msgs
            append_file(self.mbox_name, self.copy_name) # copy now has 6 msgs
            if execute == "package":
                archivemail.options.no_compress = 1
                archivemail.options.quiet = 1
                archivemail.archive(self.mbox_name)
            elif execute == "system":
                run = "./archivemail.py --no-compress --quiet %s" % \
                    self.mbox_name
                self.assertEqual(os.system(run), 0)
            else:
                sys.exit(1)
            assert(os.path.exists(self.mbox_name))
            self.assertEqual(os.path.getsize(self.mbox_name), 0)
            new_mode = os.stat(self.mbox_name)[stat.ST_MODE]
            self.assertEqual(self.mbox_mode, new_mode)
            archive_name = self.mbox_name + "_archive"
            assert(os.path.exists(archive_name))
            assert(filecmp.cmp(archive_name, self.copy_name, shallow=0))
            assert(not os.path.exists(archive_name + ".gz"))
            self.tearDown()

    def tearDown(self):
        archivemail.options.quiet = 0
        archivemail.options.no_compress = 0
        archive = self.mbox_name + "_archive"
        for name in (self.mbox_name, self.new_mbox, self.old_mbox, 
            self.copy_name, archive, archive + ".gz"):
            if name and os.path.exists(name):
                os.remove(name)


class TestArchiveMboxMode(unittest.TestCase):
    """file mode (permissions) of the original mbox should be preserved"""
    def setUp(self):
        archivemail.options.quiet = 1

    def testOld(self):
        """after archiving, the original mbox mode should be preserved"""
        for mode in (0666, 0664, 0660, 0640, 0600):
            self.mbox_name = make_mbox(messages=1, hours_old=(24 * 181))
            os.chmod(self.mbox_name, mode)
            archivemail.archive(self.mbox_name)
            archive_name = self.mbox_name + "_archive.gz"
            assert(os.path.exists(self.mbox_name))
            assert(os.path.exists(archive_name))
            new_mode = os.stat(self.mbox_name)[stat.ST_MODE]
            self.assertEqual(mode, stat.S_IMODE(new_mode))
            archive_mode = os.stat(archive_name)[stat.ST_MODE]
            self.assertEqual(0600, stat.S_IMODE(archive_mode))
            os.remove(archive_name)
            os.remove(self.mbox_name)

    # TODO: write a mixed case

    def testNew(self):
        """after no archiving, the original mbox mode should be preserved"""
        for mode in (0666, 0664, 0660, 0640, 0600):
            self.mbox_name = make_mbox(messages=1, hours_old=(24 * 179))
            os.chmod(self.mbox_name, mode)
            archivemail.archive(self.mbox_name)
            archive_name = self.mbox_name + "_archive.gz"
            assert(not os.path.exists(archive_name))
            assert(os.path.exists(self.mbox_name))
            new_mode = os.stat(self.mbox_name)[stat.ST_MODE]
            self.assertEqual(mode, stat.S_IMODE(new_mode))
            os.remove(self.mbox_name)

    def tearDown(self):
        archivemail.options.quiet = 0
        if os.path.exists(self.mbox_name):
            os.remove(self.mbox_name)


########## helper routines ############

def make_message(body=None, default_headers={}, hours_old=None):
    headers = copy.copy(default_headers)
    if not headers:
        headers = {}
    if not headers.has_key('Date'):
        time_message = time.time() - (60 * 60 * hours_old)
        headers['Date'] = time.asctime(time.localtime(time_message))
    if not headers.has_key('From'):
        headers['From'] = "sender@dummy.domain"        
    if not headers.has_key('To'):
        headers['To'] = "receipient@dummy.domain"        
    if not headers.has_key('Subject'):
        headers['Subject'] = "This is the subject"
    if not headers.has_key('From_'):
        headers['From_'] = "%s %s" % (headers['From'], headers['Date'])
    if not body:
        body = "This is the message body"

    msg = ""
    if headers.has_key('From_'):
        msg = msg + ("From %s\n" % headers['From_'])
        del headers['From_']
    for key in headers.keys():
        if headers[key] is not None:
            msg = msg + ("%s: %s\n" % (key, headers[key]))
    msg = msg + "\n\n" + body + "\n\n"
    return msg


def append_file(source, dest):
    """appends the file named 'source' to the file named 'dest'"""
    assert(os.path.isfile(source))
    assert(os.path.isfile(dest))
    read = open(source, "r")
    write = open(dest, "a+")
    write.writelines(read.readlines())
    read.close()
    write.close()

def make_mbox(body=None, headers=None, hours_old=0, messages=1):
    name = tempfile.mktemp()
    file = open(name, "w")
    for count in range(messages):
        msg = make_message(body=body, default_headers=headers, 
            hours_old=hours_old)
        file.write(msg)
    file.close()
    return name
    
def is_world_readable(path):
    """Return true if the path is world-readable, false otherwise"""
    assert(path)
    return (os.stat(path)[stat.ST_MODE] & stat.S_IROTH)

if __name__ == "__main__":
    unittest.main()
