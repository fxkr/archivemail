#!/usr/bin/python -tt
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

"""Archive and compress old mail in mbox-format mailboxes"""

import atexit
import fcntl
import getopt
import mailbox
import os
import re
import rfc822
import string
import sys
import tempfile
import time

# globals 
VERSION = "archivemail v0.1.0"
COPYRIGHT = """Copyright (C) 2002  Paul Rodger <paul@paulrodger.com>
This is free software; see the source for copying conditions. There is NO
warranty; not even for MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE."""

options = None  # global instance of the run-time options class
stale = None    # list of files to delete on abnormal exit

############## class definitions ###############

class Stats:
    """collect and print statistics per mailbox"""
    archived = 0
    mailbox_name = None
    archive_name = None
    start_time = 0
    total = 0

    def __init__(self, mailbox_name, final_archive_name):
        """constructor for a new set of statistics - the mailbox names are
           only used for printing a friendly message"""
        self.start_time = time.time()
        self.mailbox_name = mailbox_name
        self.archive_name = final_archive_name + options.compressor_extension

    def another_message(self):
        self.total = self.total + 1

    def another_archived(self):
        self.archived = self.archived + 1

    def display(self):
        """Display one line of archive statistics for the mailbox"""
        end_time = time.time()
        time_seconds = end_time - self.start_time
        action = "archived"
        if options.delete_old_mail:
            action = "deleted"
        print "%s: %s %d of %d message(s) in %.1f seconds" % \
            (self.mailbox_name, action, self.archived, self.total,
            time_seconds)
            

class StaleFiles:
    """container for remembering stale files to delete on abnormal exit"""
    archive            = None  # tempfile for messages to be archived
    compressed_archive = None  # compressed version of the above
    procmail_lock      = None  # original_mailbox.lock
    retain             = None  # tempfile for messages to be retained


class Options:
    """container for storing and setting our runtime options"""
    archive_suffix       = "_archive"
    compressor           = None
    compressor_extension = None
    days_old_max         = 180
    delete_old_mail      = 0
    lockfile_attempts    = 5     # 5 seconds of waiting
    lockfile_extension   = ".lock"
    quiet                = 0
    script_name          = os.path.basename(sys.argv[0])
    verbose              = 0

    def parse_args(self, args, usage):
        """set our runtime options from the command-line arguments"""
        try:
            opts, args = getopt.getopt(args, '?IVZd:hqs:vz', 
                             ["bzip2", "compress", "days=", "delete", "gzip", 
                              "help", "quiet", "suffix", "verbose", 
                              "version"])
        except getopt.error, msg:
            user_error(msg)
        for o, a in opts:
            if o == '--delete':
                self.delete_old_mail = 1
            if o in ('-d', '--days'):
                self.days_old_max = string.atoi(a)
                if (self.days_old_max < 1):
                    user_error("argument to -d must be greater than zero")
                if (self.days_old_max >= 10000):
                    user_error("argument to -d must be less than 10000")
            if o in ('-h', '-?', '--help'):
                print usage
                sys.exit(0)
            if o in ('-q', '--quiet'):
                self.quiet = 1
            if o in ('-v', '--verbose'):
                self.verbose = 1
            if o in ('-s', '--suffix'):
                self.archive_suffix = a
            if o in ('-V', '--version'):
                print VERSION + "\n\n" + COPYRIGHT
                sys.exit(0)
            if o in ('-z', '--gzip'):
                if (self.compressor):
                    user_error("conflicting compression options")
                self.compressor = "gzip"
            if o in ('-Z', '--compress'):
                if (self.compressor):
                    user_error("conflicting compression options")
                self.compressor = "compress"
            if o in ('-I', '--bzip2'):
                if (self.compressor):
                    user_error("conflicting compression options")
                self.compressor = "bzip2"
        if not self.compressor:
            self.compressor = "gzip"
        extensions = {
            "compress" : ".Z",
            "gzip"     : ".gz",
            "bzip2"    : ".bz2",
            }
        self.compressor_extension = extensions[self.compressor]
        return args


class Mailbox:
    """ generic read/writable 'mbox' format mailbox file"""
    count = 0
    file = None
    mbox = None

    def __init__(self):
        """constructor: doesn't do much"""
        pass

    def store(self, msg):
        """write one message to the mbox file"""
        vprint("saving message to file '%s'" % self.file.name)
        assert(msg.unixfrom)
        self.file.write(msg.unixfrom)
        assert(msg.headers)
        self.file.writelines(msg.headers)
        self.file.write("\n")

        # The following while loop is about twice as fast in 
        # practice to 'self.file.writelines(msg.fp.readlines())'
        while 1:
            body = msg.fp.read(8192)
            if not body:
                break
            self.file.write(body)
        self.count = self.count + 1

    def unlink(self):
        """destroy the whole thing"""
        if self.file:
            file_name = self.file.name
            self.close()
            vprint("unlinking file '%s'" % self.file.name)
            os.unlink(file_name)

    def get_size(self):
        """determine file size of this mbox file"""
        assert(self.file.name)
        return os.path.getsize(self.file.name)

    def close(self):
        """close the mbox file"""
        if not self.file.closed:
            vprint("closing file '%s'" % self.file.name)
            self.file.close()

    def read_message(self):
        """read one rfc822 message object from the mbox file"""
        if not self.mbox:
            self.file.seek(0)
            self.mbox = mailbox.UnixMailbox(self.file)
            assert(self.mbox)
        message = self.mbox.next()
        return message

    def exclusive_lock(self):
        """set an advisory lock on the whole mbox file"""
        vprint("obtaining exclusive lock on file '%s'" % self.file.name)
        fcntl.flock(self.file, fcntl.LOCK_EX)

    def exclusive_unlock(self):
        """unset any advisory lock on the mbox file"""
        vprint("dropping exclusive lock on file '%s'" % self.file.name)
        fcntl.flock(self.file, fcntl.LOCK_UN)

    def procmail_lock(self):
        """create a procmail-style .lock file to prevent clashes"""
        lock_name = self.file.name + options.lockfile_extension
        attempt = 0
        while os.path.isfile(lock_name):
            vprint("lockfile '%s' exists - sleeping..." % lock_name)
            time.sleep(1)
            attempt = attempt + 1
            if (attempt >= options.lockfile_attempts):
                user_error("Giving up waiting for procmail lock '%s'" % lock_name)
        vprint("writing lockfile '%s'" % lock_name)
        lock = open(lock_name, "w")
        stale.procmail_lock = lock_name
        lock.close()

    def procmail_unlock(self):
        """delete our procmail-style .lock file"""
        lock_name = self.file.name + options.lockfile_extension
        vprint("removing lockfile '%s'" % lock_name)
        os.unlink(lock_name)
        stale.procmail_lock = None

    def leave_empty(self):
        """This should be the same as 'cp /dev/null mailbox'.
           This will leave a zero-length mailbox file so that mail
           reading programs don't get upset that the mailbox has been
           completely deleted."""
        vprint("turning '%s' into a zero-length file" % self.file.name)
        atime = os.path.getatime(self.file.name)
        mtime = os.path.getmtime(self.file.name)
        blank_file = open(self.file.name, "w")
        blank_file.close()
        os.utime(self.file.name, (atime, mtime)) # reset to original timestamps



class RetainMailbox(Mailbox):
    """a temporary mailbox for holding messages that will be retained in the
       original mailbox"""
    def __init__(self):
        """constructor - create the temporary file"""
        temp_name = tempfile.mktemp("archivemail_retain")
        self.file = open(temp_name, "w")
        stale.retain = temp_name
        vprint("opened temporary retain file '%s'" % self.file.name)

    def finalise(self, final_name):
        """constructor - create the temporary file"""
        self.close()

        atime = os.path.getatime(final_name)
        mtime = os.path.getmtime(final_name)

        vprint("renaming '%s' to '%s'" % (self.file.name, final_name))
        os.rename(self.file.name, final_name)

        os.utime(final_name, (atime, mtime)) # reset to original timestamps
        stale.retain = None

    def unlink(self):
        """Override the base-class version, removing from stalefiles"""
        Mailbox.unlink(self)
        stale.retain = None


class ArchiveMailbox(Mailbox):
    """all messages that are too old go here"""
    final_name = None # this is 
    def __init__(self, final_name):
        """copy any pre-existing compressed archive to a temp file which we 
           use as the new soon-to-be compressed archive"""
        assert(final_name)
        compressor = options.compressor
        compressedfilename = final_name + options.compressor_extension
       
        if os.path.isfile(final_name):
            user_error("There is already a file named '%s'!" % (final_name))

        temp_name = tempfile.mktemp("archivemail_archive")

        if os.path.isfile(compressedfilename):
            vprint("file already exists that is named: %s" % compressedfilename)
            uncompress =  "%s -d -c %s > %s" % (compressor, 
                compressedfilename, temp_name)
            vprint("running uncompressor: %s" % uncompress)
            stale.archive = temp_name
            system_or_die(uncompress)

        stale.archive = temp_name
        self.file = open(temp_name, "a")
        self.final_name = final_name

    def finalise(self):
        """rename the temp file back to the original compressed archive
           file"""
        self.close()
        compressor = options.compressor
        compressed_archive_name = self.file.name + options.compressor_extension
        compress = compressor + " " + self.file.name
        vprint("running compressor: '%s'" % compress)

        stale.compressed_archive = compressed_archive_name
        system_or_die(compress)
        stale.archive = None

        compressed_final_name = self.final_name + options.compressor_extension
        vprint("renaming '%s' to '%s'" % (compressed_archive_name, 
            compressed_final_name))
        os.rename(compressed_archive_name, compressed_final_name)
        stale.compressed_archive = None


class OriginalMailbox(Mailbox):
    """This is the mailbox that we read messages from to determine if they are
       too old. We will never write to this file directly except at the end
       where we override the whole file with the RetainMailbox."""
    file = None
    def __init__(self, mailbox_name):
        """open the mailbox, ready for reading"""
        try:
            self.file = open(mailbox_name, "r")
        except IOError, msg:
            user_error(msg)


def main(args = sys.argv[1:]):
    global options
    global stale

    options = Options()
    usage = """Usage: %s [options] mailbox [mailbox...]
Moves old mail messages in mbox-format mailboxes to compressed mailbox
archives. This is useful for saving space and keeping your mailbox manageable.
  Options are as follows:
  -d, --days=<days>    archive messages older than <days> days (default: %d)
  -s, --suffix=<name>  suffix for archive filename (default: '%s')
  -z, --gzip           compress the archive using gzip (default) 
  -I, --bzip2          compress the archive using bzip2
  -Z, --compress       compress the archive using compress
      --delete         delete rather than archive old mail (use with caution!)
  -v, --verbose        report lots of extra debugging information
  -q, --quiet          quiet mode - print no statistics (suitable for crontab)
  -V, --version        display version information
  -h, --help           display this message
Example: %s linux-devel
  This will move all messages older than %s days to a file called 
  'linux-devel_archive.gz', deleting them from the original 'linux-devel'
  mailbox. If the 'linux-devel_archive.gz' mailbox already exists, the 
  newly archived messages are appended.
""" % (options.script_name, options.days_old_max, options.archive_suffix, 
       options.script_name, options.days_old_max)

    check_python_version()

    args = options.parse_args(args, usage)
    if len(args) == 0:
        print usage
        sys.exit(1)

    os.umask(077) # saves setting permissions on mailboxes/tempfiles
    stale = StaleFiles()
    atexit.register(clean_up)

    for filename in args:
        tempfile.tempdir = os.path.dirname(filename) # don't use /var/tmp
        final_archive_name = filename + options.archive_suffix
        archive_mailbox(mailbox_name = filename, 
                        final_archive_name = final_archive_name)



######## errors and debug ##########

def vprint(string):
    """this saves putting 'if (verbose) print foo' everywhere"""
    if options.verbose:
        print string


def user_error(string):
    """fatal error, probably something the user did wrong"""
    script_name = options.script_name
    message = "%s: %s\n" % (script_name, string)

    sys.stderr.write(message)
    sys.exit(1)

########### operations on a message ############

def is_too_old(message):
    """return true if a message is too old (and should be archived), 
       false otherwise"""
    date = message.getdate('Date')
    delivery_date = message.getdate('Delivery-date')
    use_date = None
    time_message = None

    if delivery_date:
        try:
            time_message = time.mktime(delivery_date)
            use_date = delivery_date
            vprint("using message 'Delivery-date' header")
        except ValueError:
            pass
    if date and not use_date:
        try:
            time_message = time.mktime(date)
            use_date = date
            vprint("using message 'Date' header")
        except ValueError:
            pass
    if not use_date:
        print message
        vprint("no valid dates found for message")
        return 0  
       
    time_now = time.time()
    if time_message > time_now:
        time_string = time.asctime(use_date)
        vprint("warning: message has date in the future: %s !" % time_string)
        return 0

    secs_old_max = (options.days_old_max * 24 * 60 * 60)
    days_old = (time_now - time_message) / 24 / 60 / 60
    vprint("message is %.2f days old" % days_old)

    if ((time_message + secs_old_max) < time_now):
        return 1
    return 0


###############  mailbox operations ###############

def archive_mailbox(mailbox_name, final_archive_name):
    """process and archive the given mailbox name"""
    archive = None
    retain = None
    
    vprint("archiving '%s' to '%s' ..." % (mailbox_name, final_archive_name))
    stats = Stats(mailbox_name, final_archive_name)

    original = OriginalMailbox(mailbox_name)
    if original.get_size() == 0:
        original.close()
        vprint("skipping '%s' because it is a zero-length file" % 
            original.file.name)
        if not options.quiet:
            stats.display()
        return
    original.procmail_lock()
    original.exclusive_lock()

    msg = original.read_message()
    if not msg:
       user_error("file '%s' is not in 'mbox' format" % mailbox.file.name) 

    while (msg):
        stats.another_message()
        message_id = msg.get('Message-ID')
        vprint("processing message '%s'" % message_id)
        if is_too_old(msg):
            stats.another_archived()
            if options.delete_old_mail:
                vprint("decision: delete message")
            else:
                vprint("decision: archive message")
                if (not archive):
                    archive = ArchiveMailbox(final_archive_name)
                archive.store(msg)
        else:
            vprint("decision: retain message")
            if (not retain):
                retain = RetainMailbox()
            retain.store(msg)
        msg = original.read_message()
    vprint("finished reading messages") 

    original.exclusive_unlock()
    original.close()

    if options.delete_old_mail:
        # we will never have an archive file
        if retain:
            retain.finalise(mailbox_name)
        else:
            original.leave_empty()
    elif archive:
        archive.finalise()
        if retain:
            retain.finalise(mailbox_name)
        else:
            original.leave_empty()
    else:
        # There was nothing to archive
        if retain:
            # retain will be the same as original mailbox -- no point copying
            retain.close()
            retain.unlink()

    original.procmail_unlock()
    if not options.quiet:
        stats.display()


###############  misc  functions  ###############

def clean_up():
    """This is run on exit to make sure we haven't left any stale
    files/lockfiles left on the system"""
    vprint("cleaning up ...")
    if stale.procmail_lock:
        vprint("removing stale procmail lock '%s'" % stale.procmail_lock)
        try: os.unlink(stale.procmail_lock)
        except (IOError, OSError): pass
    if stale.retain:
        vprint("removing stale retain file '%s'" % stale.retain)
        try: os.unlink(stale.retain)
        except (IOError, OSError): pass
    if stale.archive:
        vprint("removing stale archive file '%s'" % stale.archive)
        try: os.unlink(stale.archive)
        except (IOError, OSError): pass
    if stale.compressed_archive:
        vprint("removing stale compressed archive file '%s'" %
            stale.compressed_archive)
        try: os.unlink(stale.compressed_archive)
        except (IOError, OSError): pass


def check_python_version():
    """make sure we are running with the right version of python"""
    build = sys.version
    too_old_error = "requires python v2.0 or greater. Your version is: %s" % build
    try: 
        version = sys.version_info  # we might not even have this function! :)
        if (version[0] < 2):
            UserError(too_old_error)
    except:  # I should be catching more specific exceptions
        UserError(too_old_error)
        

def system_or_die(command):
    """Give a user_error() if the command we ran returned a non-zero status"""
    rv = os.system(command)
    if (rv != 0):
        status = os.WEXITSTATUS(rv)
        user_error("command '%s' returned status %d" % (command, status))


# this is where it all happens, folks
if __name__ == '__main__':
    main()
