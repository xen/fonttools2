#! /usr/bin/env python

import sys
import os
import glob
from fontTools.ttLib import identifierToTag


tablesDir = os.path.join(os.path.dirname(os.getcwd()), "Lib", "fontTools",
		"ttLib", "tables")

names = glob.glob1(tablesDir, "*.py")

modules = []
for name in names:
	try:
		tag = identifierToTag(name[:-3])
	except:
		pass
	else:
		modules.append(name[:-3])

modules.sort()

file = open(os.path.join(tablesDir, "__init__.py"), "w")

file.write("def _moduleFinderHint():\n")
file.write('\t"""Dummy function to let modulefinder know what tables may be\n')
file.write('\tdynamically imported. Generated by MetaTools/buildTableList.py.\n')
file.write('\t"""\n')
for module in modules:
	file.write("\timport %s\n" % module)

file.close()
