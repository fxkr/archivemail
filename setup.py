#!/usr/bin/env python

import sys
from distutils.core import setup

# check version
if sys.version_info[0] < 2:
    print "Python versions below 2.0 not supported"
    sys.exit(1)

setup(name="archivemail",
      version="0.3.0",
      description="archivemail - archive and compress old email",
      author="Paul Rodger",
      author_email="paul@paulrodger.com",
      url="http://archivemail.sourceforge.net/",
      scripts=["archivemail"],
      )
