#!/usr/bin/env python

import archivemail
import os
import tempfile
import unittest

class TempfileTestCase(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
