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
"""
Archive and compress old mail in mbox, MH or maildir-format mailboxes.
Website: http://archivemail.sourceforge.net/
"""

# global administrivia 
__version__ = "archivemail v0.4.9"
__cvs_id__ = "$Id$"
__copyright__ = """Copyright (C) 2002  Paul Rodger <paul@paulrodger.com>
This is free software; see the source for copying conditions. There is NO
warranty; not even for MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE."""

import sys

def check_python_version(): 
    """Abort if we are running on python < v2.0"""
    too_old_error = """This program requires python v2.0 or greater. 
Your version of python is: %s""" % sys.version
    try: 
        version = sys.version_info  # we might not even have this function! :)
        if (version[0] < 2):
            print too_old_error
            sys.exit(1)
    except AttributeError:
        print too_old_error
        sys.exit(1)

check_python_version()  # define & run this early because 'atexit' is new

import atexit
import fcntl
import getopt
import gzip
import mailbox
import os
import re
import rfc822
import shutil
import signal
import stat
import string
import tempfile
import time

############## class definitions ###############

class Stats:
    """Class to collect and print statistics about mailbox archival"""
    __archived = 0
    __mailbox_name = None
    __archive_name = None
    __start_time = 0
    __total = 0

    def __init__(self, mailbox_name, final_archive_name):
        """Constructor for a new set of statistics.

        Arguments: 
        mailbox_name -- filename/dirname of the original mailbox
        final_archive_name -- filename for the final 'mbox' archive, without
                              compression extension (eg .gz)

        """
        assert(mailbox_name)
        assert(final_archive_name)
        self.__start_time = time.time()
        self.__mailbox_name = mailbox_name
        self.__archive_name = final_archive_name + ".gz"

    def another_message(self):
        """Add one to the internal count of total messages processed"""
        self.__total = self.__total + 1

    def another_archived(self):
        """Add one to the internal count of messages archived"""
        self.__archived = self.__archived + 1

    def display(self):
        """Print statistics about how many messages were archived"""
        end_time = time.time()
        time_seconds = end_time - self.__start_time
        action = "archived"
        if options.delete_old_mail:
            action = "deleted"
        if options.dry_run:
            action = "I would have " + action
        print "%s: %s %d of %d message(s) in %.1f seconds" % \
            (self.__mailbox_name, action, self.__archived, self.__total,
            time_seconds)
            

class StaleFiles:
    """Class to keep track of files to be deleted on abnormal exit"""
    archive            = None  # tempfile for messages to be archived
    procmail_lock      = None  # original_mailbox.lock
    retain             = None  # tempfile for messages to be retained
    temp_dir           = None  # our tempfile directory container

    def clean(self):
        """Delete any temporary files or lockfiles that exist"""
        if self.procmail_lock:
            vprint("removing stale procmail lock '%s'" % self.procmail_lock)
            try: os.remove(self.procmail_lock)
            except (IOError, OSError): pass
        if self.retain:
            vprint("removing stale retain file '%s'" % self.retain)
            try: os.remove(self.retain)
            except (IOError, OSError): pass
        if self.archive:
            vprint("removing stale archive file '%s'" % self.archive)
            try: os.remove(self.archive)
            except (IOError, OSError): pass
        if self.temp_dir:
            vprint("removing stale tempfile directory '%s'" % self.temp_dir)
            try: os.rmdir(self.temp_dir)
            except (IOError, OSError): pass


class Options:
    """Class to store runtime options, including defaults"""
    archive_suffix       = "_archive"
    days_old_max         = 180
    date_old_max         = None
    delete_old_mail      = 0
    dry_run              = 0
    include_flagged      = 0
    lockfile_attempts    = 5  
    lockfile_extension   = ".lock"
    lockfile_sleep       = 1 
    no_compress          = 0
    only_archive_read    = 0
    output_dir           = None
    preserve_unread      = 0
    quiet                = 0
    read_buffer_size     = 8192
    script_name          = os.path.basename(sys.argv[0])
    min_size             = None
    verbose              = 0
    warn_duplicates      = 0

    def parse_args(self, args, usage):
        """Set our runtime options from the command-line arguments.

        Arguments:
        args -- this is sys.argv[1:]
        usage -- a usage message to display on '--help' or bad arguments

        Returns the remaining command-line arguments that have not yet been
        parsed as a string.

        """
        try:
            opts, args = getopt.getopt(args, '?D:S:Vd:hno:qs:uv', 
                             ["date=", "days=", "delete", "dry-run", "help",
                             "include-flagged", "no-compress", "output-dir=",
                             "preserve-unread", "quiet", "size=", "suffix=",
                             "verbose", "version", "warn-duplicate"])
        except getopt.error, msg:
            user_error(msg)

        archive_by = None 

        for o, a in opts:
            if o == '--delete':
                self.delete_old_mail = 1
            if o == '--include-flagged':
                self.include_flagged = 1
            if o == '--no-compress':
                self.no_compress = 1
            if o == '--warn-duplicate':
                self.warn_duplicates = 1
            if o in ('-D', '--date'):
                if archive_by: 
                    user_error("you cannot specify both -d and -D options")
                archive_by = "date"                        
                self.date_old_max = self.date_argument(a)
            if o in ('-d', '--days'):
                if archive_by: 
                    user_error("you cannot specify both -d and -D options")
                archive_by = "days"                        
                self.days_old_max = string.atoi(a)
            if o in ('-o', '--output-dir'):
                self.output_dir = a
            if o in ('-h', '-?', '--help'):
                print usage
                sys.exit(0)
            if o in ('-n', '--dry-run'):
                self.dry_run = 1
            if o in ('-q', '--quiet'):
                self.quiet = 1
            if o in ('-s', '--suffix'):
                self.archive_suffix = a
            if o in ('-S', '--size'):
                self.min_size = string.atoi(a)
            if o in ('-u', '--preserve-unread'):
                self.preserve_unread = 1
            if o in ('-v', '--verbose'):
                self.verbose = 1
            if o in ('-V', '--version'):
                print __version__ + "\n\n" + __copyright__
                sys.exit(0)
        return args

    def sanity_check(self):
        """Complain bitterly about our options now rather than later"""
        if self.output_dir:
            if not os.path.isdir(self.output_dir):
                user_error("output directory does not exist: '%s'" % \
                    self.output_dir)
            if not os.access(self.output_dir, os.W_OK):
                user_error("no write permission on output directory: '%s'" % \
                    self.output_dir)
            if is_world_writable(self.output_dir):
                unexpected_error(("output directory is world-writable: " + \
                    "%s -- I feel nervous!") % self.output_dir)
        if self.days_old_max < 1:
            user_error("--days argument must be greater than zero")
        if self.days_old_max >= 10000:
            user_error("--days argument must be less than 10000")
        if self.min_size is not None and self.min_size < 1:
            user_error("--size argument must be greater than zero")
        if self.quiet and self.verbose:
            user_error("you cannot use both the --quiet and --verbose options")

    def date_argument(self, string):
        """Converts a date argument string into seconds since the epoch"""
        date_formats = (
            "%Y-%m-%d",  # ISO format 
            "%d %b %Y" , # Internet format 
            "%d %B %Y" , # Internet format with full month names
        )
        time.accept2dyear = 0  # I'm not going to support 2-digit years
        for format in date_formats:
            try:
                date = time.strptime(string, format)
                seconds = time.mktime(date)
                return seconds
            except (ValueError, OverflowError):
                pass
        user_error("cannot parse the date argument '%s'\n"
            "The date should be in ISO format (eg '2002-04-23'),\n"
            "Internet format (eg '23 Apr 2002') or\n"
            "Internet format with full month names (eg '23 April 2002')" % 
            string)


class Mbox(mailbox.UnixMailbox):
    """Class that allows read/write access to a 'mbox' mailbox. 
    Subclasses the mailbox.UnixMailbox class.
    """
    mbox_file = None   # file handle for the mbox file
    mbox_file_name = None   # GzipFile class has no .name variable
    mbox_file_closed = 0   # GzipFile class has no .closed variable
    original_atime = None # last-accessed timestamp
    original_mtime = None # last-modified timestamp
    original_mode = None # file permissions to preserve
    starting_size = None # file size of mailbox on open

    def __init__(self, path, mode="r"):
        """Constructor for opening an existing 'mbox' mailbox.
        Extends constructor for mailbox.UnixMailbox()

        Named Arguments:
        path -- file name of the 'mbox' file to be opened
        mode -- mode to open the file in (default is read-only)

        """
        assert(path)
        try:
            self.original_atime = os.path.getatime(path)
            self.original_mtime = os.path.getmtime(path)
            self.original_mode = os.stat(path)[stat.ST_MODE]
            self.starting_size = os.path.getsize(path)
            self.mbox_file = open(path, mode)
        except IOError, msg:
            unexpected_error(msg)
        self.mbox_file_name = path
        mailbox.UnixMailbox.__init__(self, self.mbox_file)

    def write(self, msg):
        """Write a rfc822 message object to the 'mbox' mailbox.
        If the rfc822 has no Unix 'From_' line, then one is constructed
        from other headers in the message.

        Arguments:
        msg -- rfc822 message object to be written

        """
        assert(msg)
        assert(self.mbox_file)

        vprint("saving message to file '%s'" % self.mbox_file_name)
        unix_from = msg.unixfrom
        if not unix_from:
            unix_from = make_mbox_from(msg)
        self.mbox_file.write(unix_from)
        assert(msg.headers)
        self.mbox_file.writelines(msg.headers)
        self.mbox_file.write(os.linesep)

        # The following while loop is about twice as fast in 
        # practice to 'self.mbox_file.writelines(msg.fp.readlines())'
        assert(options.read_buffer_size > 0)
        while 1:
            body = msg.fp.read(options.read_buffer_size)
            if not body:
                break
            self.mbox_file.write(body)

    def remove(self):
        """Close and delete the 'mbox' mailbox file"""
        file_name = self.mbox_file_name
        self.close()
        vprint("removing file '%s'" % self.mbox_file_name)
        os.remove(file_name)

    def is_empty(self):
        """Return true if the 'mbox' file is empty, false otherwise"""
        return (os.path.getsize(self.mbox_file_name) == 0)

    def close(self):
        """Close the mbox file"""
        if not self.mbox_file_closed:
            vprint("closing file '%s'" % self.mbox_file_name)
            self.mbox_file.close()
        self.mbox_file_closed = 1 

    def reset_stat(self):
        """Set the file timestamps and mode to the original value"""
        assert(self.original_atime)
        assert(self.original_mtime)
        assert(self.mbox_file_name)
        assert(self.original_mode) # I doubt this will be 000?
        os.utime(self.mbox_file_name, (self.original_atime,  \
            self.original_mtime)) 
        os.chmod(self.mbox_file_name, self.original_mode)

    def exclusive_lock(self):
        """Set an advisory lock on the 'mbox' mailbox"""
        vprint("obtaining exclusive lock on file '%s'" % self.mbox_file_name)
        fcntl.flock(self.mbox_file.fileno(), fcntl.LOCK_EX)

    def exclusive_unlock(self):
        """Unset any advisory lock on the 'mbox' mailbox"""
        vprint("dropping exclusive lock on file '%s'" % self.mbox_file_name)
        fcntl.flock(self.mbox_file.fileno(), fcntl.LOCK_UN)

    def procmail_lock(self):
        """Create a procmail lockfile on the 'mbox' mailbox"""
        lock_name = self.mbox_file_name + options.lockfile_extension
        attempt = 0
        while os.path.isfile(lock_name):
            vprint("lockfile '%s' exists - sleeping..." % lock_name)
            time.sleep(options.lockfile_sleep)
            attempt = attempt + 1
            if (attempt >= options.lockfile_attempts):
                unexpected_error("Giving up waiting for procmail lock '%s'" 
                    % lock_name)
        vprint("writing lockfile '%s'" % lock_name)
        old_umask = os.umask(022) # is this dodgy?
        lock = open(lock_name, "w")
        _stale.procmail_lock = lock_name
        lock.close()
        old_umask = os.umask(old_umask)

    def procmail_unlock(self):
        """Delete the procmail lockfile on the 'mbox' mailbox"""
        assert(self.mbox_file_name)
        lock_name = self.mbox_file_name + options.lockfile_extension
        vprint("removing lockfile '%s'" % lock_name)
        os.remove(lock_name)
        _stale.procmail_lock = None

    def leave_empty(self):
        """Replace the 'mbox' mailbox with a zero-length file.
        This should be the same as 'cp /dev/null mailbox'.
        This will leave a zero-length mailbox file so that mail
        reading programs don't get upset that the mailbox has been
        completely deleted."""
        assert(os.path.isfile(self.mbox_file_name))
        vprint("turning '%s' into a zero-length file" % self.mbox_file_name)
        blank_file = open(self.mbox_file_name, "w")
        blank_file.close()

    def get_size(self):
        """Return the current size of the mbox file"""
        return os.path.getsize(self.mbox_file_name)


class RetainMbox(Mbox):
    """Class for holding messages that will be retained from the original
    mailbox (ie. the messages are not considered 'old'). Extends the 'Mbox'
    class. This 'mbox' file starts off as a temporary file but will eventually
    overwrite the original mailbox if everything is OK. 
    
    """
    __final_name = None

    def __init__(self, final_name):
        """Constructor - create a temporary file for the mailbox.
       
        Arguments:
        final_name -- the name of the original mailbox that this mailbox
                      will replace when we call finalise()

        """
        assert(final_name)
        temp_name = tempfile.mktemp("retain")
        self.mbox_file = open(temp_name, "w")
        self.mbox_file_name = temp_name
        _stale.retain = temp_name
        vprint("opened temporary retain file '%s'" % self.mbox_file_name)
        self.__final_name = final_name

    def finalise(self):
        """Overwrite the original mailbox with this temporary mailbox."""
        assert(self.__final_name)
        self.close()

        # make sure that the retained mailbox has the same timestamps and 
        # permission as the original mailbox
        atime = os.path.getatime(self.__final_name)
        mtime = os.path.getmtime(self.__final_name)
        mode =  os.stat(self.__final_name)[stat.ST_MODE]
        os.chmod(self.mbox_file_name, mode)

        vprint("renaming '%s' to '%s'" % (self.mbox_file_name, self.__final_name))
        try:
            os.rename(self.mbox_file_name, self.__final_name)
        except OSError:
            # file might be on a different filesystem -- move it manually
            shutil.copy2(self.mbox_file_name, self.__final_name)
            os.remove(self.mbox_file_name)
        os.utime(self.__final_name, (atime, mtime)) # reset to original timestamps
        _stale.retain = None

    def remove(self):
        """Delete this temporary mailbox. Overrides Mbox.remove()"""
        Mbox.remove(self)
        _stale.retain = None


class ArchiveMbox(Mbox):
    """Class for holding messages that will be archived from the original
    mailbox (ie. the messages that are considered 'old'). Extends the 'Mbox'
    class. This 'mbox' file starts off as a temporary file, copied from any
    pre-existing archive. It will eventually overwrite the original archive
    mailbox if everything is OK. 
    
    """
    __final_name = None 

    def __init__(self, final_name):
        """Constructor -- copy any pre-existing compressed archive to a
        temporary file which we use as the new 'mbox' archive for this
        mailbox. 
       
        Arguments:
        final_name -- the final name for this archive mailbox. This function
                      will check to see if the filename already exists, and
                      copy it to a temporary file if it does. It will also
                      rename itself to this name when we call finalise()

        """
        assert(final_name)
        if options.no_compress:
            self.__init_uncompressed(final_name)
        else:
            self.__init_compressed(final_name)
        self.__final_name = final_name

    def __init_uncompressed(self, final_name):
        """Used internally by __init__ when archives are uncompressed"""
        assert(final_name)
        compressed_archive = final_name + ".gz"
        if os.path.isfile(compressed_archive):
            unexpected_error("""There is already a file named '%s'!
Have you been previously compressing this archive? You probably should 
uncompress it manually, and try running me again.""" % compressed_archive)
        temp_name = tempfile.mktemp("archive")
        if os.path.isfile(final_name):
            vprint("file already exists that is named: %s" % final_name)
            shutil.copy2(final_name, temp_name)
        _stale.archive = temp_name
        self.mbox_file = open(temp_name, "a")
        self.mbox_file_name = temp_name

    def __init_compressed(self, final_name):
        """Used internally by __init__ when archives are compressed"""
        assert(final_name)
        compressed_filename = final_name + ".gz"
        if os.path.isfile(final_name):
            unexpected_error("""There is already a file named '%s'!
Have you been reading this archive? You probably should re-compress it
manually, and try running me again.""" % final_name)

        temp_name = tempfile.mktemp("archive.gz")
        if os.path.isfile(compressed_filename):
            vprint("file already exists that is named: %s" %  \
                compressed_filename)
            shutil.copy2(compressed_filename, temp_name)
        _stale.archive = temp_name
        self.mbox_file = gzip.GzipFile(temp_name, "a")
        self.mbox_file_name = temp_name

    def finalise(self):
        """Close the archive and rename this archive temporary file to the
        final archive filename, overwriting any pre-existing archive if it
        exists.

        """
        assert(self.__final_name)
        self.close()
        final_name = self.__final_name
        if not options.no_compress:
            final_name = final_name + ".gz"
        vprint("renaming '%s' to '%s'" % (self.mbox_file_name, 
            final_name))
        try:
            os.rename(self.mbox_file_name, final_name)
        except OSError:
            # file might be on a different filesystem -- move it manually
            shutil.copy2(self.mbox_file_name, final_name)
            os.remove(self.mbox_file_name)
        _stale.archive = None


class IdentityCache:
    """Class used to remember Message-IDs and warn if they are seen twice"""
    seen_ids = {}
    mailbox_name = None

    def __init__(self, mailbox_name):
        """Constructor: takes the mailbox name as an argument"""
        assert(mailbox_name)
        self.mailbox_name = mailbox_name

    def warn_if_dupe(self, msg):
        """Print a warning message if the message has already appeared"""
        assert(msg)
        message_id = msg.get('Message-ID')
        assert(message_id)
        if self.seen_ids.has_key(message_id):
            user_warning("duplicate message id: '%s' in mailbox '%s'" % 
                (message_id, self.mailbox_name))
        self.seen_ids[message_id] = 1


# global class instances
options = Options()  # the run-time options object
_stale = StaleFiles() # remember what we have to delete on abnormal exit


def main(args = sys.argv[1:]):
    global _stale

    # this usage message is longer than 24 lines -- bad idea?
    usage = """Usage: %s [options] mailbox [mailbox...]
Moves old mail in mbox, MH or maildir-format mailboxes to an mbox-format
mailbox compressed with gzip. 

Options are as follows:
  -d, --days=NUM        archive messages older than NUM days (default: %d)
  -D, --date=DATE       archive messages older than DATE
  -o, --output-dir=DIR  directory to store archives (default: same as original)
  -s, --suffix=NAME     suffix for archive filename (default: '%s')
  -S, --size=NUM        only archive messages NUM bytes or larger
  -n, --dry-run         don't write to anything - just show what would be done
  -u, --preserve-unread never archive unread messages
      --delete          delete rather than archive old mail (use with caution!)
      --include-flagged messages flagged important can also be archived
      --no-compress     do not compress archives with gzip
      --warn-duplicate  warn about duplicate Message-IDs in the same mailbox
  -v, --verbose         report lots of extra debugging information
  -q, --quiet           quiet mode - print no statistics (suitable for crontab)
  -V, --version         display version information
  -h, --help            display this message

Example: %s linux-kernel
  This will move all messages older than %s days to a 'mbox' mailbox called 
  'linux-kernel_archive.gz', deleting them from the original 'linux-kernel'
  mailbox. If the 'linux-kernel_archive.gz' mailbox already exists, the 
  newly archived messages are appended.

Website: http://archivemail.sourceforge.net/ """ %   \
    (options.script_name, options.days_old_max, options.archive_suffix,
    options.script_name, options.days_old_max)

    args = options.parse_args(args, usage)
    if len(args) == 0:
        print usage
        sys.exit(1)

    options.sanity_check()

    for mailbox_path in args:
        archive(mailbox_path)


######## errors and debug ##########

def vprint(string):
    """Print the string argument if we are in verbose mode"""
    if options.verbose:
        print string


def unexpected_error(string):
    """Print the string argument, a 'shutting down' message and abort - 
    this function never returns"""
    sys.stderr.write("%s: %s\n" % (options.script_name, string))
    sys.stderr.write("%s: unexpected error encountered - shutting down\n" % 
        options.script_name)
    sys.exit(1)


def user_error(string):
    """Print the string argument and abort - this function never returns"""
    sys.stderr.write("%s: %s\n" % (options.script_name, string))
    sys.exit(1)


def user_warning(string):
    """Print the string argument"""
    sys.stderr.write("%s: Warning - %s\n" % (options.script_name, string))

########### operations on a message ############

def make_mbox_from(message):
    """Return a string suitable for use as a 'From_' mbox header for the
    message.

    Arguments:
    message -- the rfc822 message object

    """
    assert(message)
    address_header = message.get('Return-path')
    if not address_header:
        vprint("make_mbox_from: no Return-path -- using 'From:' instead!")
        address_header = message.get('From')
    (name, address) = rfc822.parseaddr(address_header)

    time_message = guess_delivery_time(message)
    assert(time_message)
    gm_date = time.gmtime(time_message)
    assert(gm_date)
    date_string = time.asctime(gm_date)

    mbox_from = "From %s %s\n" % (address, date_string)
    return mbox_from


def guess_delivery_time(message):
    """Return a guess at the delivery date of an rfc822 message""" 
    assert(message)
    # try to guess the delivery date from various headers
    # get more desparate as we go through the array
    for header in ('Delivery-date', 'Date', 'Resent-Date'):
        try:
            date = message.getdate(header)
            if date:
                time_message = time.mktime(date)
                vprint("using valid time found from '%s' header" % header)
                return time_message
        except (IndexError, ValueError, OverflowError): pass
    # as a second-last resort, try the date from the 'From_' line (ugly)
    # this will only work from a mbox-format mailbox
    if (message.unixfrom):
        header = re.sub("From \S+", "", message.unixfrom)
        header = string.strip(header)
        date = rfc822.parsedate(header)
        if date:
            try:
                time_message = time.mktime(date)
                assert(time_message)
                vprint("using valid time found from unix 'From_' header")
                return time_message
            except (ValueError, OverflowError): pass
    # the headers have no valid dates -- last resort, try the file timestamp
    # this will not work for mbox mailboxes
    try:
        file_name = message.fp.name
    except AttributeError:
        # we are looking at a 'mbox' mailbox - argh! 
        # Just return the current time - this will never get archived :(
        vprint("no valid times found at all -- using current time!")
        return time.time()
    if not os.path.isfile(file_name):
        unexpected_error("mailbox file name '%s' has gone missing" % \
            file_name)    
    time_message = os.path.getmtime(message.fp.name)
    vprint("using valid time found from '%s' last-modification time" % \
        file_name)
    return time_message
   

def add_status_headers(message):
    """
    Add Status and X-Status headers to a message from a maildir mailbox.

    Maildir messages store their information about being read/replied/etc in
    the suffix of the filename rather than in Status and X-Status headers in
    the message. In order to archive maildir messages into mbox format, it is
    nice to preserve this information by putting it into the status headers.

    """
    status = ""
    x_status = ""
    match = re.search(":2,(.+)$", message.fp.name)
    if match:
        flags = match.group(1)
        for flag in flags: 
            if flag == "D": # (draft): the user considers this message a draft
                pass # does this make any sense in mbox? 
            elif flag == "F": # (flagged): user-defined 'important' flag
                x_status = x_status + "F"
            elif flag == "R": # (replied): the user has replied to this message
                x_status = x_status + "A"
            elif flag == "S": # (seen): the user has viewed this message
                status = status + "R"
            elif flag == "T": # (trashed): user has moved this message to trash
                pass # is this Status: D ? 
            else:
                pass # no whingeing here, although it could be a good experiment

    # files in the maildir 'cur' directory are no longer new,
    # they are the same as messages with 'Status: O' headers in mbox
    (None, last_dir) = os.path.split(os.path.dirname(message.fp.name))
    if last_dir == "cur":
        status = status + "O" 

    # Maildir messages should not already have 'Status' and 'X-Status'
    # headers, although I have seen it done. If they do already have them, just
    # preserve them rather than trying to overwrite/verify them.
    if not message.get('Status') and status:
        vprint("converting maildir status into Status header '%s'" % status)
        message['Status'] = status
    if not message.get('X-Status') and x_status:
        vprint("converting maildir status into X-Status header '%s'" % x_status)
        message['X-Status'] = x_status


def is_flagged(message):
    """return true if the message is flagged important, false otherwise"""
    # MH and mbox mailboxes use the 'X-Status' header to indicate importance
    x_status = message.get('X-Status')
    if x_status and re.search('F', x_status):
        vprint("message is important (X-Status header='%s')" % x_status)
        return 1
    file_name = None
    try:
        file_name = message.fp.name
    except AttributeError:
        pass
    # maildir mailboxes use the filename suffix to indicate flagged status
    if file_name and re.search(":2,.*F.*$", file_name):
        vprint("message is important (filename info has 'F')")
        return 1
    vprint("message is not flagged important")
    return 0


def is_unread(message):
    """return true if the message is unread, false otherwise"""
    # MH and mbox mailboxes use the 'Status' header to indicate read status
    status = message.get('Status')
    if status and re.search('R', status):
        vprint("message has been read (status header='%s')" % status)
        return 0
    file_name = None
    try:
        file_name = message.fp.name
    except AttributeError:
        pass
    # maildir mailboxes use the filename suffix to indicate read status
    if file_name and re.search(":2,.*S.*$", file_name):
        vprint("message has been read (filename info has 'S')")
        return 0
    vprint("message is unread")
    return 1


def is_smaller(message, size):
    """Return true if the message is smaller than size bytes, false otherwise"""
    assert(message)
    assert(size > 0)
    file_name = None
    message_size = None
    try:
        file_name = message.fp.name
    except AttributeError:
        pass
    if file_name:
        # with maildir and MH mailboxes, we can just use the file size
        message_size = os.path.getsize(file_name)
    else:
        # with mbox mailboxes, not so easy
        message_size = 0
        if message.unixfrom:
            message_size = message_size + len(message.unixfrom)
        for header in message.headers:
            message_size = message_size + len(header)
        message_size = message_size + 1 # the blank line after the headers
        start_offset = message.fp.tell()
        message.fp.seek(0, 2) # seek to the end of the message
        end_offset = message.fp.tell()
        message.rewindbody()
        message_size = message_size + (end_offset - start_offset)
    if message_size < size:
        vprint("message is too small (%d bytes), minimum bytes : %d" % \
            (message_size, size))
        return 1
    else:
        vprint("message is not too small (%d bytes), minimum bytes: %d" % \
            (message_size, size))
        return 0


def should_archive(message):
    """Return true if we should archive the message, false otherwise"""
    old = 0
    time_message = guess_delivery_time(message)
    if options.date_old_max == None:
        old = is_older_than_days(time_message, options.days_old_max)
    else:
        old = is_older_than_time(time_message, options.date_old_max)

    # I could probably do this in one if statement, but then I wouldn't
    # understand it. 
    if not old:
        return 0
    if not options.include_flagged and is_flagged(message):
        return 0
    if options.min_size and is_smaller(message, options.min_size):
        return 0
    if options.preserve_unread and is_unread(message):
        return 0
    return 1
        
    
def is_older_than_time(time_message, max_time):
    """Return true if a message is older than the specified time,
    false otherwise.

    Arguments:
    time_message -- the delivery date of the message measured in seconds
                    since the epoch
    max_time -- maximum time allowed for message
       
    """
    days_old = (max_time - time_message) / 24 / 60 / 60
    if time_message < max_time:
        vprint("message is %.2f days older than the specified date" % days_old)
        return 1
    vprint("message is %.2f days younger than the specified date" % \
        abs(days_old))
    return 0


def is_older_than_days(time_message, max_days):
    """Return true if a message is older than the specified number of days,
    false otherwise.

    Arguments:
    time_message -- the delivery date of the message measured in seconds
                    since the epoch
    max_days -- maximum number of days before message is considered old
       
    """
    assert(max_days >= 1)

    time_now = time.time()
    if time_message > time_now:
        vprint("warning: message has date in the future")
        return 0
    secs_old_max = (max_days * 24 * 60 * 60)
    days_old = (time_now - time_message) / 24 / 60 / 60
    vprint("message is %.2f days old" % days_old)
    if ((time_message + secs_old_max) < time_now):
        return 1
    return 0


###############  mailbox operations ###############

def archive(mailbox_name):
    """Archives a mailbox.

    Arguments:
    mailbox_name -- the filename/dirname of the mailbox to be archived
    final_archive_name -- the filename of the 'mbox' mailbox to archive
                          old messages to - appending if the archive 
                          already exists

    """
    assert(mailbox_name) 

    # strip any trailing slash (we could be archiving a maildir or MH format
    # mailbox and somebody was pressing <tab> in bash) - we don't want to use
    # the trailing slash in the archive name
    mailbox_name = re.sub("/$", "", mailbox_name)
    assert(mailbox_name) 

    set_signal_handlers()
    os.umask(077) # saves setting permissions on mailboxes/tempfiles

    # allow the user to embed time formats such as '%B' in the suffix string
    parsed_suffix = time.strftime(options.archive_suffix, 
        time.localtime(time.time()))

    final_archive_name = mailbox_name + parsed_suffix
    if options.output_dir:
        final_archive_name = os.path.join(options.output_dir, 
                os.path.basename(final_archive_name))
    vprint("archiving '%s' to '%s' ..." % (mailbox_name, final_archive_name))

    # create a temporary directory for us to work in securely
    old_temp_dir = tempfile.tempdir
    tempfile.tempdir = None
    new_temp_dir = tempfile.mktemp('archivemail')
    assert(new_temp_dir)
    os.mkdir(new_temp_dir)
    _stale.temp_dir = new_temp_dir
    tempfile.tempdir = new_temp_dir

    vprint("set tempfile directory to '%s'" % new_temp_dir)

    # check to see if we are running as root -- if so, change our effective
    # userid and groupid to that of the original mailbox
    if (os.getuid() == 0) and os.path.exists(mailbox_name):
        mailbox_user = os.stat(mailbox_name)[stat.ST_UID]
        mailbox_group = os.stat(mailbox_name)[stat.ST_GID]
        vprint("changing effective group id to: %d" % mailbox_group)
        os.setegid(mailbox_group)
        vprint("changing effective user id to: %d" % mailbox_user)
        os.seteuid(mailbox_user)

    if os.path.islink(mailbox_name):
        unexpected_error("'%s' is a symbolic link -- I feel nervous!" % 
            mailbox_name)
    elif os.path.isfile(mailbox_name):
        vprint("guessing mailbox is of type: mbox")
        _archive_mbox(mailbox_name, final_archive_name)
    elif os.path.isdir(mailbox_name):
        cur_path = os.path.join(mailbox_name, "cur")
        new_path = os.path.join(mailbox_name, "new")
        if os.path.isdir(cur_path) and os.path.isdir(new_path):
            vprint("guessing mailbox is of type: maildir")
            _archive_dir(mailbox_name, final_archive_name, "maildir")
        else:
            vprint("guessing mailbox is of type: MH")
            _archive_dir(mailbox_name, final_archive_name, "mh")
    else:
        user_error("'%s': no such file or directory" % mailbox_name)

    # if we are running as root, revert the seteuid()/setegid() above
    if (os.getuid() == 0):
        vprint("changing effective groupid and userid back to root")
        os.setegid(0)
        os.seteuid(0)
    os.rmdir(new_temp_dir)
    _stale.temp_dir = None
    tempfile.tempdir = old_temp_dir


def _archive_mbox(mailbox_name, final_archive_name):
    """Archive a 'mbox' style mailbox - used by archive_mailbox()

    Arguments:
    mailbox_name -- the filename/dirname of the mailbox to be archived
    final_archive_name -- the filename of the 'mbox' mailbox to archive
                          old messages to - appending if the archive 
                          already exists
    """
    assert(mailbox_name)
    assert(final_archive_name)

    archive = None
    retain = None
    stats = Stats(mailbox_name, final_archive_name)
    original = Mbox(path=mailbox_name)
    cache = IdentityCache(mailbox_name)

    original.procmail_lock()
    original.exclusive_lock()
    msg = original.next()
    if not msg and (original.starting_size > 0):
        user_error("'%s' is not a valid mbox-format mailbox" % mailbox_name)
    while (msg):
        stats.another_message()
        vprint("processing message '%s'" % msg.get('Message-ID'))
        if options.warn_duplicates:
            cache.warn_if_dupe(msg)             
        if should_archive(msg):
            stats.another_archived()
            if options.delete_old_mail:
                vprint("decision: delete message")
            else:
                vprint("decision: archive message")
                if not options.dry_run:
                    if (not archive):
                        archive = ArchiveMbox(final_archive_name)
                    archive.write(msg)
        else:
            vprint("decision: retain message")
            if not options.dry_run:
                if (not retain):
                    retain = RetainMbox(mailbox_name)
                retain.write(msg)
        msg = original.next()
    vprint("finished reading messages") 
    original.exclusive_unlock()
    original.close()
    if original.starting_size != original.get_size():
        unexpected_error("the mailbox '%s' changed size during reading!" % \
           mailbox_name)         
    original.reset_stat()
    if not options.dry_run:
        if retain: retain.close()
        if archive: archive.close()
        if options.delete_old_mail:
            # we will never have an archive file
            if retain:
                retain.finalise()
            else:
                # nothing was retained - everything was deleted
                original.leave_empty()
                original.reset_stat()
        elif archive:
            archive.finalise()
            if retain:
                retain.finalise()
            else:
                # nothing was retained - everything was deleted
                original.leave_empty()
                original.reset_stat()
        else:
            # There was nothing to archive
            if retain:
                # retain will be the same as original mailbox 
                retain.remove()
    original.procmail_unlock()
    if not options.quiet:
        stats.display()


def _archive_dir(mailbox_name, final_archive_name, type):
    """Archive a 'maildir' or 'MH' style mailbox - used by archive_mailbox()"""
    assert(mailbox_name)
    assert(final_archive_name)
    assert(type)
    original = None
    archive = None
    stats = Stats(mailbox_name, final_archive_name)
    delete_queue = []

    if type == "maildir":
        original = mailbox.Maildir(mailbox_name)
    elif type == "mh":
        original = mailbox.MHMailbox(mailbox_name)
    else:
        unexpected_error("unknown type: %s" % type)        
    assert(original)

    cache = IdentityCache(mailbox_name)

    msg = original.next()
    while (msg):
        stats.another_message()
        vprint("processing message '%s'" % msg.get('Message-ID'))
        if options.warn_duplicates:
            cache.warn_if_dupe(msg)             
        if should_archive(msg):
            stats.another_archived()
            if options.delete_old_mail:
                vprint("decision: delete message")
            else:
                vprint("decision: archive message")
                if not options.dry_run:
                    if not archive:
                        archive = ArchiveMbox(final_archive_name)
                    if type == "maildir":
                        add_status_headers(msg)
                    archive.write(msg)
            if not options.dry_run: delete_queue.append(msg.fp.name) 
        else:
            vprint("decision: retain message")
        msg = original.next()
    vprint("finished reading messages") 
    if not options.dry_run:
        if archive:
            archive.close()
            archive.finalise()
        for file_name in delete_queue:
            if os.path.isfile(file_name):
                vprint("removing original message: '%s'" % file_name)
                os.remove(file_name)
    if not options.quiet:
        stats.display()


###############  misc  functions  ###############


def set_signal_handlers():
    """set signal handlers to clean up temporary files on unexpected exit"""
    # Make sure we clean up nicely - we don't want to leave stale procmail
    # lockfiles about if something bad happens to us. This is quite 
    # important, even though procmail will delete stale files after a while.
    atexit.register(clean_up) # delete stale files on exceptions/normal exit
    signal.signal(signal.SIGHUP, clean_up_signal)   # signal 1
    # SIGINT (signal 2) is handled as a python exception
    signal.signal(signal.SIGQUIT, clean_up_signal)  # signal 3
    signal.signal(signal.SIGTERM, clean_up_signal)  # signal 15


def clean_up():
    """Delete stale files -- to be registered with atexit.register()"""
    vprint("cleaning up ...")
    _stale.clean()


def clean_up_signal(signal_number, stack_frame):
    """Delete stale files -- to be registered as a signal handler.

    Arguments:
    signal_number -- signal number of the terminating signal
    stack_frame -- the current stack frame
    
    """
    # this will run the above clean_up(), since unexpected_error()
    # will abort with sys.exit() and clean_up will be registered 
    # at this stage
    unexpected_error("received signal %s" % signal_number)


def is_world_writable(path):
    """Return true if the path is world-writable, false otherwise""" 
    assert(path)
    return (os.stat(path)[stat.ST_MODE] & stat.S_IWOTH)


# this is where it all happens, folks
if __name__ == '__main__':
    main()
