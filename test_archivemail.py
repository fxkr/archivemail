#! /usr/bin/env python
############################################################################
# Copyright (C) 2002  Paul Rodger <paul@paulrodger.com>
#           (C) 2006-2008  Nikolaus Schulz <microschulz@web.de>
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
    * archiving maildir-format mailboxes
    * archiving MH-format mailboxes
    * preservation of status information from maildir to mbox
    * a 3rd party process changing the mbox file being read

"""

import sys

def check_python_version(): 
    """Abort if we are running on python < v2.3"""
    too_old_error = "This test script requires python version 2.3 or later. " + \
      "Your version of python is:\n%s" % sys.version
    try: 
        version = sys.version_info  # we might not even have this function! :)
        if (version[0] < 2) or (version[0] == 2 and version[1] < 3):
            print too_old_error
            sys.exit(1)
    except AttributeError:
        print too_old_error
        sys.exit(1)

# define & run this early because 'unittest' requires Python >= 2.1
check_python_version()  

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
import gzip
import cStringIO
import rfc822

try:
    import archivemail
except ImportError:
    print "The archivemail script needs to be called 'archivemail.py'"
    print "and should be in the current directory in order to be imported"
    print "and tested. Sorry."
    if os.path.isfile("archivemail"):
        print "Try renaming it from 'archivemail' to 'archivemail.py'."
    sys.exit(1)

# precision of os.utime() when restoring mbox timestamps
utimes_precision = 5


class TestCaseInTempdir(unittest.TestCase):
    """Base class for testcases that need to create temporary files. 
    All testcases that create temporary files should be derived from this
    class, not directly from unittest.TestCase.
    TestCaseInTempdir provides these methods:
    
    setUp()     Creates a safe temporary directory and sets tempfile.tempdir.
                
    tearDown()  Recursively removes the temporary directory and unsets
                tempfile.tempdir.

    Overriding methods should call the ones above."""
    temproot = None

    def setUp(self):
        if not self.temproot:
            assert(not tempfile.tempdir)
            self.temproot = tempfile.tempdir = \
                tempfile.mkdtemp(prefix="test-archivemail")
     
    def tearDown(self):
        assert(tempfile.tempdir == self.temproot)
        if self.temproot:
            shutil.rmtree(self.temproot)
            tempfile.tempdir = self.temproot = None


############ Mbox Class testing ##############

class TestMboxProcmailLock(TestCaseInTempdir):
    def setUp(self):
        super(TestMboxProcmailLock, self).setUp()
        self.mbox_name = make_mbox()
        self.mbox_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.mbox = archivemail.Mbox(self.mbox_name)

    def testProcmailLock(self):
        """procmail_lock/unlock should create/delete a lockfile"""
        lock = self.mbox_name + ".lock"
        self.mbox.procmail_lock()
        assert(os.path.isfile(lock))
        self.mbox.procmail_unlock()
        assert(not os.path.isfile(lock))

class TestMboxExclusiveLock(TestCaseInTempdir):
    def setUp(self):
        super(TestMboxExclusiveLock, self).setUp()
        self.mbox_name = make_mbox()
        self.mbox = archivemail.Mbox(self.mbox_name)

    def testExclusiveLock(self):
        """exclusive_lock/unlock should create/delete an advisory lock"""
        
        # We're using flock(2) locks; these aren't completely portable, and on
        # some systems (e.g. Solaris) they may be emulated with fcntl(2) locks,
        # which have pretty different semantics.  We could test real flock
        # locks within this process, but that doesn't work for fcntl locks.  
        #
        # The following code snippet heavily lends from the Python 2.5 mailbox
        # unittest.
        # BEGIN robbery:

        # Fork off a subprocess that will lock the file for 2 seconds,
        # unlock it, and then exit.
        pid = os.fork()
        if pid == 0:
            # In the child, lock the mailbox.
            self.mbox.exclusive_lock()
            time.sleep(2)
            self.mbox.exclusive_unlock()
            os._exit(0)

        # In the parent, sleep a bit to give the child time to acquire
        # the lock.
        time.sleep(0.5)
        # The parent's file self.mbox.mbox_file shares flock locks with the
        # duplicated FD in the child; reopen it so we get a different file
        # table entry.
        file = open(self.mbox_name, "r+")
        lock_nb = fcntl.LOCK_EX | fcntl.LOCK_NB
        fd = file.fileno()
        try:
            self.assertRaises(IOError, fcntl.flock, fd, lock_nb)

        finally:
            # Wait for child to exit.  Locking should now succeed.
            exited_pid, status = os.waitpid(pid, 0)

        fcntl.flock(fd, lock_nb)
        fcntl.flock(fd, fcntl.LOCK_UN)
        # END robbery


class TestMboxNext(TestCaseInTempdir):
    def setUp(self):
        super(TestMboxNext, self).setUp()
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


############ TempMbox Class testing ##############

class TestTempMboxWrite(TestCaseInTempdir):
    def setUp(self):
        super(TestTempMboxWrite, self).setUp()

    def testWrite(self):
        """mbox.write() should append messages to a mbox mailbox"""
        read_file = make_mbox(messages=3)
        mbox_read = archivemail.Mbox(read_file)
        mbox_write = archivemail.TempMbox()
        write_file = mbox_write.mbox_file_name
        for count in range(3):
            msg = mbox_read.next()
            mbox_write.write(msg)
        mbox_read.close()
        mbox_write.close()
        assert(filecmp.cmp(read_file, write_file, shallow=0))

    def testWriteNone(self):
        """calling mbox.write() with no message should raise AssertionError"""
        write = archivemail.TempMbox()
        self.assertRaises(AssertionError, write.write, None)

class TestTempMboxRemove(TestCaseInTempdir):
    def setUp(self):
        super(TestTempMboxRemove, self).setUp()
        self.mbox = archivemail.TempMbox()
        self.mbox_name = self.mbox.mbox_file_name

    def testMboxRemove(self):
        """remove() should delete a mbox mailbox"""
        assert(os.path.exists(self.mbox_name))
        self.mbox.remove()
        assert(not os.path.exists(self.mbox_name))



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
        self.assertEqual(archivemail.options.delete_old_mail, 0)

    def testNoCompress(self):
        """no-compression should be off by default"""
        self.assertEqual(archivemail.options.no_compress, 0)

    def testIncludeFlagged(self):
        """we should not archive flagged messages by default"""
        self.assertEqual(archivemail.options.include_flagged, 0)

    def testPreserveUnread(self):
        """we should not preserve unread messages by default"""
        self.assertEqual(archivemail.options.preserve_unread, 0)

class TestOptionParser(unittest.TestCase):
    def setUp(self):
        self.oldopts = copy.copy(archivemail.options)

    def testOptionDate(self):
        """--date and -D options are parsed correctly"""
        date_formats = (
            "%Y-%m-%d",  # ISO format
            "%d %b %Y" , # Internet format
            "%d %B %Y" , # Internet format with full month names
        )
        date = time.strptime("2000-07-29", "%Y-%m-%d")
        unixdate = time.mktime(date)
        for df in date_formats:
            d = time.strftime(df, date)
            for opt in '-D', '--date=':
                archivemail.options.date_old_max = None
                archivemail.options.parse_args([opt+d], "")
                self.assertEqual(unixdate, archivemail.options.date_old_max)

    def testOptionPreserveUnread(self):
        """--preserve-unread option is parsed correctly"""
        archivemail.options.parse_args(["--preserve-unread"], "")
        assert(archivemail.options.preserve_unread)
        archivemail.options.preserve_unread = 0
        archivemail.options.parse_args(["-u"], "")
        assert(archivemail.options.preserve_unread)

    def testOptionSuffix(self):
        """--suffix and -s options are parsed correctly"""
        for suffix in ("_static_", "_%B_%Y", "-%Y-%m-%d"):
            archivemail.options.parse_args(["--suffix="+suffix], "")
            assert(archivemail.options.archive_suffix == suffix)
            archivemail.options.suffix = None
            archivemail.options.parse_args(["-s", suffix], "")
            assert(archivemail.options.archive_suffix == suffix)

    def testOptionDryrun(self):
        """--dry-run option is parsed correctly"""
        archivemail.options.parse_args(["--dry-run"], "")
        assert(archivemail.options.dry_run)
        archivemail.options.preserve_unread = 0
        archivemail.options.parse_args(["-n"], "")
        assert(archivemail.options.dry_run)

    def testOptionDays(self):
        """--days and -d options are parsed correctly"""
        archivemail.options.parse_args(["--days=11"], "")
        self.assertEqual(archivemail.options.days_old_max, 11)
        archivemail.options.days_old_max = None
        archivemail.options.parse_args(["-d11"], "")
        self.assertEqual(archivemail.options.days_old_max, 11)

    def testOptionDelete(self):
        """--delete option is parsed correctly"""
        archivemail.options.parse_args(["--delete"], "")
        assert(archivemail.options.delete_old_mail)

    def testOptionCopy(self):
        """--copy option is parsed correctly"""
        archivemail.options.parse_args(["--copy"], "")
        assert(archivemail.options.copy_old_mail)

    def testOptionOutputdir(self):
        """--output-dir and -o options are parsed correctly"""
        for path in "/just/some/path", "relative/path":
            archivemail.options.parse_args(["--output-dir=%s" % path], "")
            self.assertEqual(archivemail.options.output_dir, path)
            archivemail.options.output_dir = None
            archivemail.options.parse_args(["-o%s" % path], "")
            self.assertEqual(archivemail.options.output_dir, path)

    def testOptionNocompress(self):
        """--no-compress option is parsed correctly"""
        archivemail.options.parse_args(["--no-compress"], "")
        assert(archivemail.options.no_compress)

    def testOptionSize(self):
        """--size and -S options are parsed correctly"""
        size = "666"
        archivemail.options.parse_args(["--size=%s" % size ], "")
        self.assertEqual(archivemail.options.min_size, int(size))
        archivemail.options.parse_args(["-S%s" % size ], "")
        self.assertEqual(archivemail.options.min_size, int(size))

    def tearDown(self):
        archivemail.options = self.oldopts

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

########## archivemail.parse_imap_url() unit testing #################

class TestParseIMAPUrl(unittest.TestCase): 
    def setUp(self):
        archivemail.options.quiet = 1
        archivemail.options.verbose = 0
        archivemail.options.pwfile = None
        
    urls_withoutpass = [
            ('imaps://user@example.org@imap.example.org/upperbox/lowerbox',
                ('user', None, 'example.org@imap.example.org',
                'upperbox/lowerbox')), 
            ('imaps://"user@example.org"@imap.example.org/upperbox/lowerbox',
                ('user@example.org', None, 'imap.example.org',
                'upperbox/lowerbox')), 
            ('imaps://user@example.org"@imap.example.org/upperbox/lowerbox',
                ('user', None, 'example.org"@imap.example.org',
                'upperbox/lowerbox')), 
            ('imaps://"user@example.org@imap.example.org/upperbox/lowerbox',
                ('"user', None, 'example.org@imap.example.org',
                'upperbox/lowerbox')), 
            ('imaps://"us\\"er@example.org"@imap.example.org/upperbox/lowerbox',
                ('us"er@example.org', None, 'imap.example.org',
                'upperbox/lowerbox')), 
            ('imaps://user\\@example.org@imap.example.org/upperbox/lowerbox',
                ('user\\', None, 'example.org@imap.example.org',
                'upperbox/lowerbox'))
    ]
    urls_withpass = [
            ('imaps://user@example.org:passwd@imap.example.org/upperbox/lowerbox',
                ('user@example.org', 'passwd', 'imap.example.org',
                'upperbox/lowerbox'), 
                ('user', None, 'example.org:passwd@imap.example.org',
                'upperbox/lowerbox')), 
            ('imaps://"user@example.org:passwd@imap.example.org/upperbox/lowerbox',
                ('"user@example.org', "passwd", 'imap.example.org',
                'upperbox/lowerbox'), 
                ('"user', None, 'example.org:passwd@imap.example.org',
                'upperbox/lowerbox')), 
            ('imaps://u\\ser\\@example.org:"p@sswd"@imap.example.org/upperbox/lowerbox', 
                ('u\\ser\\@example.org', 'p@sswd', 'imap.example.org',
                'upperbox/lowerbox'),
                ('u\\ser\\', None, 'example.org:"p@sswd"@imap.example.org',
                'upperbox/lowerbox'))
    ]
    # These are invalid when the password's not stripped. 
    urls_onlywithpass = [
            ('imaps://"user@example.org":passwd@imap.example.org/upperbox/lowerbox',
                ('user@example.org', "passwd", 'imap.example.org',
                'upperbox/lowerbox'))
    ]
    def testUrlsWithoutPwfile(self):
        """Parse test urls with --pwfile option unset. This parses a password in
        the URL, if present."""
        archivemail.options.pwfile = None
        for mbstr in self.urls_withpass + self.urls_withoutpass:
            url = mbstr[0][mbstr[0].find('://')+3:]
            result = archivemail.parse_imap_url(url)
            self.assertEqual(result, mbstr[1])

    def testUrlsWithPwfile(self):
        """Parse test urls with --pwfile set.  In this case the ':' character
        loses its meaning as a delimiter."""
        archivemail.options.pwfile = "whocares.txt"
        for mbstr in self.urls_withpass: 
            url = mbstr[0][mbstr[0].find('://')+3:]
            result = archivemail.parse_imap_url(url)
            self.assertEqual(result, mbstr[2])
        for mbstr in self.urls_onlywithpass: 
            url = mbstr[0][mbstr[0].find('://')+3:]
            self.assertRaises(archivemail.UnexpectedError, 
                    archivemail.parse_imap_url, url)

    def tearDown(self): 
        archivemail.options.quiet = 0
        archivemail.options.verbose = 0
        archivemail.options.pwfile = None

########## acceptance testing ###########

class TestArchiveMbox(TestCaseInTempdir):
    """archiving should work based on the date of messages given"""
    old_mbox = None
    new_mbox = None
    copy_name = None
    mbox_name = None

    def setUp(self):
        self.oldopts = copy.copy(archivemail.options)
        archivemail.options.quiet = 1
        super(TestArchiveMbox, self).setUp()
 
    def testOld(self):
        """archiving an old mailbox"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181))
        self.mbox_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.copy_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        self.assertEqual(os.path.getsize(self.mbox_name), 0)
        new_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.assertEqual(self.mbox_mode, new_mode)
        archive_name = self.mbox_name + "_archive.gz"
        assertEqualContent(archive_name, self.copy_name, zipfirst=True)

    def testOldFromInBody(self):
        """archiving an old mailbox with 'From ' in the body"""
        body = """This is a message with ^From at the start of a line
From is on this line
This is after the ^From line"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181), body=body)
        self.copy_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        self.assertEqual(os.path.getsize(self.mbox_name), 0)
        archive_name = self.mbox_name + "_archive.gz"
        assertEqualContent(archive_name, self.copy_name, zipfirst=True)

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
            msg = make_message(default_headers=headers, wantobj=True)
            date = time.strptime("2000-07-29", "%Y-%m-%d")
            archivemail.options.date_old_max = time.mktime(date)
            assert(archivemail.should_archive(msg))
            date = time.strptime("2000-07-27", "%Y-%m-%d")
            archivemail.options.date_old_max = time.mktime(date)
            assert(not archivemail.should_archive(msg))

    def testMixed(self):
        """archiving a mixed mailbox"""
        self.new_mbox = make_mbox(messages=3, hours_old=(24 * 179))
        self.old_mbox = make_mbox(messages=3, hours_old=(24 * 181))
        self.mbox_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.new_mbox, self.mbox_name)
        append_file(self.old_mbox, self.mbox_name)
        archivemail.archive(self.mbox_name)
        assertEqualContent(self.mbox_name, self.new_mbox)
        archive_name = self.mbox_name + "_archive.gz"
        assertEqualContent(archive_name, self.old_mbox, zipfirst=True)

    def testNew(self):
        """archiving a new mailbox"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 179))
        self.mbox_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.copy_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.archive(self.mbox_name)
        assertEqualContent(self.mbox_name, self.copy_name)
        new_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.assertEqual(self.mbox_mode, new_mode)
        archive_name = self.mbox_name + "_archive.gz"
        assert(not os.path.exists(archive_name))


    def testOldExisting(self):
        """archiving an old mailbox with an existing archive"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181))
        self.mbox_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.copy_name = tempfile.mkstemp()[1]
        archive_name = self.mbox_name + "_archive.gz"
        shutil.copyfile(self.mbox_name, self.copy_name)
        fp1 = open(self.mbox_name, "r")
        fp2 = gzip.GzipFile(archive_name, "w")
        shutil.copyfileobj(fp1, fp2) # archive has 3 msgs
        fp2.close()
        fp1.close()
        append_file(self.mbox_name, self.copy_name) # copy now has 6 msgs
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        self.assertEqual(os.path.getsize(self.mbox_name), 0)
        new_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.assertEqual(self.mbox_mode, new_mode)
        assertEqualContent(archive_name, self.copy_name, zipfirst=True)

    def testOldWeirdHeaders(self):
        """archiving old mailboxes with weird headers"""
        weird_headers = (
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
            {   # completely blank dates were crashing < version 0.4.7
                'From_' : 'sender@dummy.domain Fri Jul 28 16:11:36 2000',
                'Date'  : '',
            },
            {   # completely blank dates were crashing < version 0.4.7
                'From_' : 'sender@dummy.domain Fri Jul 28 16:11:36 2000',
                'Date'  : '',
                'Resent-Date'  : '',
            },
        )
        fd, self.mbox_name = tempfile.mkstemp()
        fp = os.fdopen(fd, "w")
        for headers in weird_headers:
            msg_text = make_message(default_headers=headers)
            fp.write(msg_text*2)
        fp.close()
        self.copy_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        self.assertEqual(os.path.getsize(self.mbox_name), 0)
        archive_name = self.mbox_name + "_archive.gz"
        assertEqualContent(archive_name, self.copy_name, zipfirst=True)

    def tearDown(self):
        archivemail.options = self.oldopts
        super(TestArchiveMbox, self).tearDown()


class TestArchiveMboxTimestamp(TestCaseInTempdir):
    """original mbox timestamps should always be preserved"""
    def setUp(self):
        super(TestArchiveMboxTimestamp, self).setUp() 
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
        self.assertAlmostEqual(self.mtime, new_mtime, utimes_precision)
        self.assertAlmostEqual(self.atime, new_atime, utimes_precision)

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
        self.assertAlmostEqual(self.mtime, new_mtime, utimes_precision)
        self.assertAlmostEqual(self.atime, new_atime, utimes_precision)

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
        self.assertAlmostEqual(self.mtime, new_mtime, utimes_precision)
        self.assertAlmostEqual(self.atime, new_atime, utimes_precision)

    def tearDown(self):
        archivemail.options.quiet = 0
        super(TestArchiveMboxTimestamp, self).tearDown()


class TestArchiveMboxAll(TestCaseInTempdir): 
    def setUp(self):
        super(TestArchiveMboxAll, self).setUp()
        archivemail.options.quiet = 1
        archivemail.options.archive_all = 1

    def testNew(self):
        """archiving --all messages in a new mailbox""" 
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 179))
        self.mbox_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.copy_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.archive(self.mbox_name)
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

    def tearDown(self):
        archivemail.options.quiet = 0
        archivemail.options.archive_all = 0
        super(TestArchiveMboxAll, self).tearDown()

class TestArchiveMboxPreserveStatus(TestCaseInTempdir):
    """make sure the 'preserve_unread' option works"""
    def setUp(self):
        super(TestArchiveMboxPreserveStatus, self).setUp()
        archivemail.options.quiet = 1
        archivemail.options.preserve_unread = 1

    def testOldRead(self):
        """archiving an old read mailbox should create an archive"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181), \
            headers={"Status":"RO"})
        self.copy_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        self.assertEqual(os.path.getsize(self.mbox_name), 0)
        archive_name = self.mbox_name + "_archive.gz"
        assertEqualContent(archive_name, self.copy_name, zipfirst=True)

    def testOldUnread(self):
        """archiving an unread mailbox should not create an archive"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181))
        self.copy_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.archive(self.mbox_name)
        assertEqualContent(self.mbox_name, self.copy_name)
        archive_name = self.mbox_name + "_archive.gz"
        assert(not os.path.exists(archive_name))

    def tearDown(self):
        archivemail.options.quiet = 0
        archivemail.options.preserve_unread = 0
        super(TestArchiveMboxPreserveStatus, self).tearDown()


class TestArchiveMboxSuffix(TestCaseInTempdir):
    """make sure the 'suffix' option works"""
    def setUp(self):
        super(TestArchiveMboxSuffix, self).setUp()
        archivemail.options.quiet = 1

    def testSuffix(self):
        """archiving with specified --suffix arguments"""
        for suffix in ("_static_", "_%B_%Y", "-%Y-%m-%d"):
            days_old_max = 180
            self.mbox_name = make_mbox(messages=3,
                hours_old=(24 * (days_old_max+1)))
            self.copy_name = tempfile.mkstemp()[1]
            shutil.copyfile(self.mbox_name, self.copy_name)
            archivemail.options.archive_suffix = suffix
            archivemail.archive(self.mbox_name)
            assert(os.path.exists(self.mbox_name))
            self.assertEqual(os.path.getsize(self.mbox_name), 0)

            parsed_suffix_time = time.time() - days_old_max*24*60*60
            parsed_suffix = time.strftime(suffix,
                time.localtime(parsed_suffix_time))

            archive_name = self.mbox_name + parsed_suffix + ".gz"
            assertEqualContent(archive_name, self.copy_name, zipfirst=True)
            os.remove(archive_name)

    def tearDown(self):
        archivemail.options.quiet = 0
        archivemail.options.archive_suffix = "_archive"
        super(TestArchiveMboxSuffix, self).tearDown()


class TestArchiveDryRun(TestCaseInTempdir):
    """make sure the 'dry-run' option works"""
    def setUp(self):
        super(TestArchiveDryRun, self).setUp()
        archivemail.options.quiet = 1
        archivemail.options.dry_run = 1

    def testOld(self):
        """archiving an old mailbox with the 'dry-run' option"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181))
        self.copy_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.archive(self.mbox_name)
        assertEqualContent(self.mbox_name, self.copy_name)
        archive_name = self.mbox_name + "_archive.gz"
        assert(not os.path.exists(archive_name))

    def tearDown(self):
        archivemail.options.dry_run = 0
        archivemail.options.quiet = 0
        super(TestArchiveDryRun, self).tearDown()


class TestArchiveDays(TestCaseInTempdir):
    """make sure the 'days' option works"""
    def setUp(self):
        super(TestArchiveDays, self).setUp()
        archivemail.options.quiet = 1

    def testOld(self):
        """specifying the 'days' option on an older mailbox"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 12))
        self.copy_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.options.days_old_max = 11
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        self.assertEqual(os.path.getsize(self.mbox_name), 0)
        archive_name = self.mbox_name + "_archive.gz"
        assertEqualContent(archive_name, self.copy_name, zipfirst=True)

    def testNew(self):
        """specifying the 'days' option on a newer mailbox"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 10))
        self.copy_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.options.days_old_max = 11
        archivemail.archive(self.mbox_name)
        assertEqualContent(self.mbox_name, self.copy_name)
        archive_name = self.mbox_name + "_archive.gz"
        assert(not os.path.exists(archive_name))

    def tearDown(self):
        archivemail.options.days_old_max = 180
        archivemail.options.quiet = 0
        super(TestArchiveDays, self).tearDown()


class TestArchiveDelete(TestCaseInTempdir):
    """make sure the 'delete' option works"""
    old_mbox = None
    new_mbox = None
    copy_name = None
    mbox_name = None

    def setUp(self):
        super(TestArchiveDelete, self).setUp()
        archivemail.options.quiet = 1
        archivemail.options.delete_old_mail = 1

    def testNew(self):
        """archiving a new mailbox with the 'delete' option"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 179))
        self.copy_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.archive(self.mbox_name)
        assertEqualContent(self.mbox_name, self.copy_name)
        archive_name = self.mbox_name + "_archive.gz"
        assert(not os.path.exists(archive_name))

    def testMixed(self):
        """archiving a mixed mailbox with the 'delete' option"""
        self.new_mbox = make_mbox(messages=3, hours_old=(24 * 179))
        self.old_mbox = make_mbox(messages=3, hours_old=(24 * 181))
        self.mbox_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.new_mbox, self.mbox_name)
        append_file(self.old_mbox, self.mbox_name)
        archivemail.archive(self.mbox_name)
        assertEqualContent(self.mbox_name, self.new_mbox)
        archive_name = self.mbox_name + "_archive.gz"
        assert(not os.path.exists(archive_name))

    def testOld(self):
        """archiving an old mailbox with the 'delete' option"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181))
        self.copy_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        self.assertEqual(os.path.getsize(self.mbox_name), 0)
        archive_name = self.mbox_name + "_archive.gz"
        assert(not os.path.exists(archive_name))

    def tearDown(self):
        archivemail.options.delete_old_mail = 0
        archivemail.options.quiet = 0
        super(TestArchiveDelete, self).tearDown()


class TestArchiveCopy(TestCaseInTempdir):
    """make sure the 'copy' option works"""
    old_mbox = None
    new_mbox = None
    mbox_backup_name = None
    mbox_name = None

    def setUp(self):
        super(TestArchiveCopy, self).setUp()
        archivemail.options.quiet = 1
        archivemail.options.copy_old_mail = 1

    def testNew(self):
        """archiving a new mailbox with the 'copy' option"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 179))
        self.mbox_backup_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.mbox_backup_name)
        archivemail.archive(self.mbox_name)
        assertEqualContent(self.mbox_name, self.mbox_backup_name)
        archive_name = self.mbox_name + "_archive.gz"
        assert(not os.path.exists(archive_name))
        self.tearDown()

    def testMixed(self):
        """archiving a mixed mailbox with the 'copy' option"""
        self.new_mbox = make_mbox(messages=3, hours_old=(24 * 179))
        self.old_mbox = make_mbox(messages=3, hours_old=(24 * 181))
        self.mbox_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.new_mbox, self.mbox_name)
        append_file(self.old_mbox, self.mbox_name)
        self.mbox_backup_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.mbox_backup_name)
        archivemail.archive(self.mbox_name)
        assertEqualContent(self.mbox_name, self.mbox_backup_name)
        archive_name = self.mbox_name + "_archive.gz"
        assertEqualContent(archive_name, self.old_mbox, zipfirst=True)

    def testOld(self):
        """archiving an old mailbox with the 'copy' option"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181))
        self.mbox_backup_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.mbox_backup_name)
        archivemail.archive(self.mbox_name)
        assertEqualContent(self.mbox_name, self.mbox_backup_name)
        archive_name = self.mbox_name + "_archive.gz"
        assertEqualContent(archive_name, self.mbox_name, zipfirst=True)

    def tearDown(self):
        archivemail.options.copy_old_mail = 0
        archivemail.options.quiet = 0
        super(TestArchiveCopy, self).tearDown()


class TestArchiveMboxFlagged(TestCaseInTempdir):
    """make sure the 'include_flagged' option works"""
    def setUp(self):
        super(TestArchiveMboxFlagged, self).setUp()
        archivemail.options.include_flagged = 0
        archivemail.options.quiet = 1

    def testOld(self):
        """by default, old flagged messages should not be archived"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181), \
            headers={"X-Status":"F"})
        self.copy_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.archive(self.mbox_name)
        assertEqualContent(self.mbox_name, self.copy_name)
        archive_name = self.mbox_name + "_archive.gz"
        assert(not os.path.exists(archive_name))

    def testIncludeFlaggedNew(self):
        """new flagged messages should not be archived with include_flagged"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 179), \
            headers={"X-Status":"F"})
        self.copy_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.options.include_flagged = 1
        archivemail.archive(self.mbox_name)
        assertEqualContent(self.mbox_name, self.copy_name)
        archive_name = self.mbox_name + "_archive.gz"
        assert(not os.path.exists(archive_name))

    def testIncludeFlaggedOld(self):
        """old flagged messages should be archived with include_flagged"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181), \
            headers={"X-Status":"F"})
        self.copy_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.options.include_flagged = 1
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        self.assertEqual(os.path.getsize(self.mbox_name), 0)
        archive_name = self.mbox_name + "_archive.gz"
        assertEqualContent(archive_name, self.copy_name, zipfirst=True)

    def tearDown(self):
        archivemail.options.include_flagged = 0
        archivemail.options.quiet = 0
        super(TestArchiveMboxFlagged, self).tearDown()


class TestArchiveMboxOutputDir(TestCaseInTempdir):
    """make sure that the 'output-dir' option works"""
    def setUp(self):
        super(TestArchiveMboxOutputDir, self).setUp()
        archivemail.options.quiet = 1

    def testOld(self):
        """archiving an old mailbox with a sepecified output dir"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181))
        self.copy_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.copy_name)
        self.dir_name = tempfile.mkdtemp()
        archivemail.options.output_dir = self.dir_name
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        self.assertEqual(os.path.getsize(self.mbox_name), 0)
        archive_name = self.dir_name + "/" + \
            os.path.basename(self.mbox_name) + "_archive.gz"
        assertEqualContent(archive_name, self.copy_name, zipfirst=True)

    def tearDown(self):
        archivemail.options.quiet = 0
        archivemail.options.output_dir = None
        super(TestArchiveMboxOutputDir, self).tearDown()


class TestArchiveMboxUncompressed(TestCaseInTempdir):
    """make sure that the 'no_compress' option works"""
    mbox_name = None
    new_mbox = None
    old_mbox = None
    copy_name = None

    def setUp(self):
        archivemail.options.quiet = 1
        archivemail.options.no_compress = 1
        super(TestArchiveMboxUncompressed, self).setUp()

    def testOld(self):
        """archiving an old mailbox uncompressed"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181))
        self.mbox_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.copy_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        self.assertEqual(os.path.getsize(self.mbox_name), 0)
        new_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.assertEqual(self.mbox_mode, new_mode)
        archive_name = self.mbox_name + "_archive"
        assertEqualContent(archive_name, self.copy_name)
        assert(not os.path.exists(archive_name + ".gz"))

    def testNew(self):
        """archiving a new mailbox uncompressed"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 179))
        self.mbox_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.copy_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.archive(self.mbox_name)
        assertEqualContent(self.mbox_name, self.copy_name)
        new_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.assertEqual(self.mbox_mode, new_mode)
        archive_name = self.mbox_name + "_archive"
        assert(not os.path.exists(archive_name))
        assert(not os.path.exists(archive_name + ".gz"))

    def testMixed(self):
        """archiving a mixed mailbox uncompressed"""
        self.new_mbox = make_mbox(messages=3, hours_old=(24 * 179))
        self.old_mbox = make_mbox(messages=3, hours_old=(24 * 181))
        self.mbox_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.new_mbox, self.mbox_name)
        append_file(self.old_mbox, self.mbox_name)
        archivemail.archive(self.mbox_name)
        assertEqualContent(self.mbox_name, self.new_mbox)
        archive_name = self.mbox_name + "_archive"
        assertEqualContent(archive_name, self.old_mbox)
        assert(not os.path.exists(archive_name + ".gz"))

    def testOldExists(self):
        """archiving an old mailbox uncopressed with an existing archive"""
        self.mbox_name = make_mbox(messages=3, hours_old=(24 * 181))
        self.mbox_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.copy_name = tempfile.mkstemp()[1]
        archive_name = self.mbox_name + "_archive"
        shutil.copyfile(self.mbox_name, self.copy_name)
        shutil.copyfile(self.mbox_name, archive_name) # archive has 3 msgs
        append_file(self.mbox_name, self.copy_name) # copy now has 6 msgs
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        self.assertEqual(os.path.getsize(self.mbox_name), 0)
        new_mode = os.stat(self.mbox_name)[stat.ST_MODE]
        self.assertEqual(self.mbox_mode, new_mode)
        archive_name = self.mbox_name + "_archive"
        assertEqualContent(archive_name, self.copy_name)
        assert(not os.path.exists(archive_name + ".gz"))

    def tearDown(self):
        archivemail.options.quiet = 0
        archivemail.options.no_compress = 0
        super(TestArchiveMboxUncompressed, self).tearDown()


class TestArchiveSize(TestCaseInTempdir):
    """check that the 'size' argument works"""
    def setUp(self):
        super(TestArchiveSize, self).setUp()
        archivemail.options.quiet = 1

    def testSmaller(self):
        """giving a size argument smaller than the message"""
        self.mbox_name = make_mbox(messages=1, hours_old=(24 * 181))
        size_arg = os.path.getsize(self.mbox_name) - 1
        self.copy_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.options.min_size = size_arg
        archivemail.archive(self.mbox_name)
        assert(os.path.exists(self.mbox_name))
        self.assertEqual(os.path.getsize(self.mbox_name), 0)
        archive_name = self.mbox_name + "_archive.gz"
        assertEqualContent(archive_name, self.copy_name, zipfirst=True)

    def testBigger(self):
        """giving a size argument bigger than the message"""
        self.mbox_name = make_mbox(messages=1, hours_old=(24 * 181))
        size_arg = os.path.getsize(self.mbox_name) + 1
        self.copy_name = tempfile.mkstemp()[1]
        shutil.copyfile(self.mbox_name, self.copy_name)
        archivemail.options.min_size = size_arg
        archivemail.archive(self.mbox_name)
        assertEqualContent(self.mbox_name, self.copy_name)
        archive_name = self.mbox_name + "_archive.gz"
        assert(not os.path.exists(archive_name))

    def tearDown(self):
        archivemail.options.quiet = 0
        archivemail.options.min_size = None
        super(TestArchiveSize, self).tearDown()


class TestArchiveMboxMode(TestCaseInTempdir):
    """file mode (permissions) of the original mbox should be preserved"""
    def setUp(self):
        super(TestArchiveMboxMode, self).setUp()
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
        super(TestArchiveMboxMode, self).tearDown()


########## helper routines ############

def make_message(body=None, default_headers={}, hours_old=None, wantobj=False):
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
    if not wantobj:
        return msg
    fp = cStringIO.StringIO(msg)
    return rfc822.Message(fp)

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
    assert(tempfile.tempdir)
    fd, name = tempfile.mkstemp()
    file = os.fdopen(fd, "w")
    for count in range(messages):
        msg = make_message(body=body, default_headers=headers, 
            hours_old=hours_old)
        file.write(msg)
    file.close()
    return name

def assertEqualContent(firstfile, secondfile, zipfirst=False):
    """Verify that the two files exist and have identical content. If zipfirst
    is True, assume that firstfile is gzip-compressed."""
    assert(os.path.exists(firstfile))
    assert(os.path.exists(secondfile))
    if zipfirst:
        try:
            fp1 = gzip.GzipFile(firstfile, "r")
            fp2 = open(secondfile, "r")
            assert(cmp_fileobj(fp1, fp2))
        finally:
            fp1.close()
            fp2.close()
    else:
        assert(filecmp.cmp(firstfile, secondfile, shallow=0))

def cmp_fileobj(fp1, fp2):
    """Return if reading the fileobjects yields identical content."""
    bufsize = 8192
    while True:
        b1 = fp1.read(bufsize)
        b2 = fp2.read(bufsize)
        if b1 != b2:
            return False
        if not b1:
            return True

if __name__ == "__main__":
    unittest.main()
