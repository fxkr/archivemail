#!/usr/bin/env python

import sys

def check_python_version(): 
    """Abort if we are running on python < v2.0"""
    too_old_error = "This program requires python v2.0 or greater."
    try: 
        version = sys.version_info  # we might not even have this function! :)
        if (version[0] < 2):
            print too_old_error
            sys.exit(1)
    except AttributeError:
        print too_old_error
        sys.exit(1)

check_python_version()  # define & run this early - 'distutils.core' is new
from distutils.core import setup

setup(name="archivemail",
      version="0.4.1",
      description="archive and compress old email",
      platforms="POSIX",
      license="GNU GPL",
      url="http://archivemail.sourceforge.net/",
      author="Paul Rodger",
      author_email="paul@paulrodger.com",
      scripts=["archivemail"],
      data_files=[("man/man1", ["archivemail.1"])],
      )
