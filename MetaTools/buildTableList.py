#! /usr/bin/env python

import sys
import os
import glob
from fontTools.ttLib import identifierToTag


fontToolsDir = os.path.dirname(os.path.dirname(os.path.join(os.getcwd(), sys.argv[0])))
fontToolsDir= os.path.normpath(fontToolsDir)
tablesDir = os.path.join(fontToolsDir,
		"Lib", "fontTools", "ttLib", "tables")
docFile = os.path.join(fontToolsDir, "Doc", "documentation.html")

names = glob.glob1(tablesDir, "*.py")

modules = []
tables = []
for name in names:
	try:
		tag = identifierToTag(name[:-3])
	except:
		pass
	else:
		modules.append(name[:-3])
		tables.append(tag.strip())

modules.sort()
tables.sort()


file = open(os.path.join(tablesDir, "__init__.py"), "w")

file.write("# DON'T EDIT! This file is generated by MetaTools/buildTableList.py.\n")
file.write("def _moduleFinderHint():\n")
file.write('\t"""Dummy function to let modulefinder know what tables may be\n')
file.write('\tdynamically imported. Generated by MetaTools/buildTableList.py.\n')
file.write('\t"""\n')
for module in modules:
	file.write("\timport %s\n" % module)

file.close()


begin = "<!-- begin table list -->"
end = "<!-- end table list -->"
doc = open(docFile).read()
beginPos = doc.find(begin)
assert beginPos > 0
beginPos = beginPos + len(begin) + 1
endPos = doc.find(end)

doc = doc[:beginPos] + ", ".join(tables[:-1]) + " and " + tables[-1] + "\n" + doc[endPos:]

open(docFile, "w").write(doc)
