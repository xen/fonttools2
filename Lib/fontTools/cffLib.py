"""cffLib.py -- read/write tools for Adobe CFF fonts."""

#
# $Id: cffLib.py,v 1.28 2003-01-03 20:56:01 jvr Exp $
#

import struct, sstruct
import string
from types import FloatType, ListType, StringType, TupleType
from fontTools.misc import psCharStrings
from fontTools.misc.textTools import safeEval


DEBUG = 0


cffHeaderFormat = """
	major:   B
	minor:   B
	hdrSize: B
	offSize: B
"""

class CFFFontSet:
	
	def __init__(self):
		pass
	
	def decompile(self, file, otFont):
		sstruct.unpack(cffHeaderFormat, file.read(4), self)
		assert self.major == 1 and self.minor == 0, \
				"unknown CFF format: %d.%d" % (self.major, self.minor)
		
		file.seek(self.hdrSize)
		self.fontNames = list(Index(file))
		self.topDictIndex = TopDictIndex(file)
		self.strings = IndexedStrings(file)
		self.GlobalSubrs = GlobalSubrsIndex(file)
		self.topDictIndex.strings = self.strings
		self.topDictIndex.GlobalSubrs = self.GlobalSubrs
	
	def __len__(self):
		return len(self.fontNames)
	
	def keys(self):
		return self.fontNames[:]
	
	def values(self):
		return self.topDictIndex
	
	def __getitem__(self, name):
		try:
			index = self.fontNames.index(name)
		except ValueError:
			raise KeyError, name
		return self.topDictIndex[index]
	
	def compile(self, file, otFont):
		strings = IndexedStrings()
		writer = CFFWriter()
		writer.add(sstruct.pack(cffHeaderFormat, self))
		fontNames = Index()
		for name in self.fontNames:
			fontNames.append(name)
		writer.add(fontNames.getCompiler(strings, None))
		topCompiler = self.topDictIndex.getCompiler(strings, None)
		writer.add(topCompiler)
		writer.add(strings.getCompiler())
		writer.add(self.GlobalSubrs.getCompiler(strings, None))
		
		for topDict in self.topDictIndex:
			if not hasattr(topDict, "charset") or topDict.charset is None:
				charset = otFont.getGlyphOrder()
				topDict.charset = charset
		
		for child in topCompiler.getChildren(strings):
			writer.add(child)
		
		writer.toFile(file)
	
	def toXML(self, xmlWriter, progress=None):
		xmlWriter.newline()
		for fontName in self.fontNames:
			xmlWriter.begintag("CFFFont", name=fontName)
			xmlWriter.newline()
			font = self[fontName]
			font.toXML(xmlWriter, progress)
			xmlWriter.endtag("CFFFont")
			xmlWriter.newline()
		xmlWriter.newline()
		xmlWriter.begintag("GlobalSubrs")
		xmlWriter.newline()
		self.GlobalSubrs.toXML(xmlWriter, progress)
		xmlWriter.endtag("GlobalSubrs")
		xmlWriter.newline()
		xmlWriter.newline()
	
	def fromXML(self, (name, attrs, content)):
		if not hasattr(self, "GlobalSubrs"):
			self.GlobalSubrs = GlobalSubrsIndex()
			self.major = 1
			self.minor = 0
			self.hdrSize = 4
			self.offSize = 4  # XXX ??
		if name == "CFFFont":
			if not hasattr(self, "fontNames"):
				self.fontNames = []
				self.topDictIndex = TopDictIndex()
			fontName = attrs["name"]
			topDict = TopDict(GlobalSubrs=self.GlobalSubrs)
			topDict.charset = None  # gets filled in later
			self.fontNames.append(fontName)
			self.topDictIndex.append(topDict)
			for element in content:
				if isinstance(element, StringType):
					continue
				topDict.fromXML(element)
		elif name == "GlobalSubrs":
			for element in content:
				if isinstance(element, StringType):
					continue
				name, attrs, content = element
				subr = psCharStrings.T2CharString(None, subrs=None, globalSubrs=None)
				subr.fromXML((name, attrs, content))
				self.GlobalSubrs.append(subr)


class CFFWriter:
	
	def __init__(self):
		self.data = []
	
	def add(self, table):
		self.data.append(table)
	
	def toFile(self, file):
		lastPosList = None
		count = 1
		while 1:
			if DEBUG:
				print "CFFWriter.toFile() iteration:", count
			count = count + 1
			pos = 0
			posList = [pos]
			for item in self.data:
				if hasattr(item, "getDataLength"):
					endPos = pos + item.getDataLength()
				else:
					endPos = pos + len(item)
				if hasattr(item, "setPos"):
					item.setPos(pos, endPos)
				pos = endPos
				posList.append(pos)
			if posList == lastPosList:
				break
			lastPosList = posList
		if DEBUG:
			print "CFFWriter.toFile() writing to file."
		begin = file.tell()
		posList = [0]
		for item in self.data:
			if hasattr(item, "toFile"):
				item.toFile(file)
			else:
				file.write(item)
			posList.append(file.tell() - begin)
		assert posList == lastPosList


def calcOffSize(largestOffset):
	if largestOffset < 0x100:
		offSize = 1
	elif largestOffset < 0x10000:
		offSize = 2
	elif largestOffset < 0x1000000:
		offSize = 3
	else:
		offSize = 4
	return offSize


class IndexCompiler:
	
	def __init__(self, items, strings, parent):
		self.items = self.getItems(items, strings)
		self.parent = parent
	
	def getItems(self, items, strings):
		return items
	
	def getOffsets(self):
		pos = 1
		offsets = [pos]
		for item in self.items:
			if hasattr(item, "getDataLength"):
				pos = pos + item.getDataLength()
			else:
				pos = pos + len(item)
			offsets.append(pos)
		return offsets
	
	def getDataLength(self):
		lastOffset = self.getOffsets()[-1]
		offSize = calcOffSize(lastOffset)
		dataLength = (
			2 +                                # count
			1 +                                # offSize
			(len(self.items) + 1) * offSize +  # the offsets
			lastOffset - 1                     # size of object data
		)
		return dataLength
	
	def toFile(self, file):
		offsets = self.getOffsets()
		writeCard16(file, len(self.items))
		offSize = calcOffSize(offsets[-1])
		writeCard8(file, offSize)
		offSize = -offSize
		pack = struct.pack
		for offset in offsets:
			binOffset = pack(">l", offset)[offSize:]
			assert len(binOffset) == -offSize
			file.write(binOffset)
		for item in self.items:
			if hasattr(item, "toFile"):
				item.toFile(file)
			else:
				file.write(item)


class IndexedStringsCompiler(IndexCompiler):
	
	def getItems(self, items, strings):
		return items.strings


class TopDictIndexCompiler(IndexCompiler):
	
	def getItems(self, items, strings):
		out = []
		for item in items:
			out.append(item.getCompiler(strings, self))
		return out
	
	def getChildren(self, strings):
		children = []
		for topDict in self.items:
			children.extend(topDict.getChildren(strings))
		return children


class GlobalSubrsCompiler(IndexCompiler):
	def getItems(self, items, strings):
		out = []
		for cs in items:
			cs.compile()
			out.append(cs.bytecode)
		return out

class SubrsCompiler(GlobalSubrsCompiler):
	def setPos(self, pos, endPos):
		offset = pos - self.parent.pos
		self.parent.rawDict["Subrs"] = offset

class CharStringsCompiler(GlobalSubrsCompiler):
	def setPos(self, pos, endPos):
		self.parent.rawDict["CharStrings"] = pos


class Index:
	
	"""This class represents what the CFF spec calls an INDEX."""
	
	compilerClass = IndexCompiler
	
	def __init__(self, file=None):
		name = self.__class__.__name__
		if file is None:
			self.items = []
			return
		if DEBUG:
			print "loading %s at %s" % (name, file.tell())
		self.file = file
		count = readCard16(file)
		self.count = count
		self.items = [None] * count
		if count == 0:
			self.items = []
			return
		offSize = readCard8(file)
		if DEBUG:
			print "    index count: %s offSize: %s" % (count, offSize)
		assert offSize <= 4, "offSize too large: %s" % offSize
		self.offsets = offsets = []
		pad = '\0' * (4 - offSize)
		for index in range(count+1):
			chunk = file.read(offSize)
			chunk = pad + chunk
			offset, = struct.unpack(">L", chunk)
			offsets.append(int(offset))
		self.offsetBase = file.tell() - 1
		file.seek(self.offsetBase + offsets[-1])  # pretend we've read the whole lot
		if DEBUG:
			print "    end of %s at %s" % (name, file.tell())
	
	def __len__(self):
		return len(self.items)
	
	def __getitem__(self, index):
		item = self.items[index]
		if item is not None:
			return item
		offset = self.offsets[index] + self.offsetBase
		size = self.offsets[index+1] - self.offsets[index]
		file = self.file
		file.seek(offset)
		data = file.read(size)
		assert len(data) == size
		item = self.produceItem(index, data, file, offset, size)
		self.items[index] = item
		return item
	
	def produceItem(self, index, data, file, offset, size):
		return data
	
	def append(self, item):
		self.items.append(item)
	
	def getCompiler(self, strings, parent):
		return self.compilerClass(self, strings, parent)


class GlobalSubrsIndex(Index):
	
	compilerClass = GlobalSubrsCompiler
	
	def __init__(self, file=None, globalSubrs=None, private=None, fdSelect=None, fdArray=None):
		Index.__init__(self, file)
		self.globalSubrs = globalSubrs
		self.private = private
		self.fdSelect = fdSelect
		self.fdArray = fdArray
	
	def produceItem(self, index, data, file, offset, size):
		if self.private is not None:
			private = self.private
		elif self.fdArray is not None:
			private = self.fdArray[self.fdSelect[index]].Private
		else:
			private = None
		if hasattr(private, "Subrs"):
			subrs = private.Subrs
		else:
			subrs = []
		return psCharStrings.T2CharString(data, subrs=subrs, globalSubrs=self.globalSubrs)
	
	def toXML(self, xmlWriter, progress):
		fdSelect = self.fdSelect
		xmlWriter.comment("The 'index' attribute is only for humans; "
				"it is ignored when parsed.")
		xmlWriter.newline()
		for i in range(len(self)):
			subr = self[i]
			if subr.needsDecompilation():
				xmlWriter.begintag("CharString", index=i, raw=1)
			else:
				xmlWriter.begintag("CharString", index=i)
			xmlWriter.newline()
			subr.toXML(xmlWriter)
			xmlWriter.endtag("CharString")
			xmlWriter.newline()
	
	def fromXML(self, (name, attrs, content)):
		if name <> "CharString":
			return
		subr = psCharStrings.T2CharString(None, subrs=None, globalSubrs=None)
		subr.fromXML((name, attrs, content))
		self.append(subr)
	
	def getItemAndSelector(self, index):
		fdSelect = self.fdSelect
		if fdSelect is None:
			sel = None
		else:
			sel = fdSelect[index]
		return self[index], sel


class SubrsIndex(GlobalSubrsIndex):
	compilerClass = SubrsCompiler


class TopDictIndex(Index):
	
	compilerClass = TopDictIndexCompiler
	
	def produceItem(self, index, data, file, offset, size):
		top = TopDict(self.strings, file, offset, self.GlobalSubrs)
		top.decompile(data)
		return top
	
	def toXML(self, xmlWriter, progress):
		for i in range(len(self)):
			xmlWriter.begintag("FontDict", index=i)
			xmlWriter.newline()
			self[i].toXML(xmlWriter, progress)
			xmlWriter.endtag("FontDict")
			xmlWriter.newline()


class CharStrings:
	
	def __init__(self, file, charset, globalSubrs, private, fdSelect, fdArray):
		if file is not None:
			self.charStringsIndex = SubrsIndex(file, globalSubrs, private, fdSelect, fdArray)
			self.charStrings = charStrings = {}
			for i in range(len(charset)):
				charStrings[charset[i]] = i
			self.charStringsAreIndexed = 1
		else:
			self.charStrings = {}
			self.charStringsAreIndexed = 0
			self.globalSubrs = globalSubrs
			self.private = private
			self.fdSelect = fdSelect
			self.fdArray = fdArray
	
	def keys(self):
		return self.charStrings.keys()
	
	def values(self):
		if self.charStringsAreIndexed:
			return self.charStringsIndex
		else:
			return self.charStrings.values()
	
	def has_key(self, name):
		return self.charStrings.has_key(name)
	
	def __len__(self):
		return len(self.charStrings)
	
	def __getitem__(self, name):
		charString = self.charStrings[name]
		if self.charStringsAreIndexed:
			charString = self.charStringsIndex[charString]
		return charString
	
	def __setitem__(self, name, charString):
		if self.charStringsAreIndexed:
			index = self.charStrings[name]
			self.charStringsIndex[index] = charString
		else:
			self.charStrings[name] = charString
	
	def getItemAndSelector(self, name):
		if self.charStringsAreIndexed:
			index = self.charStrings[name]
			return self.charStringsIndex.getItemAndSelector(index)
		else:
			# XXX needs work for CID fonts
			return self.charStrings[name], None
	
	def toXML(self, xmlWriter, progress):
		names = self.keys()
		names.sort()
		i = 0
		step = 10
		numGlyphs = len(names)
		for name in names:
			charStr, fdSelect = self.getItemAndSelector(name)
			if charStr.needsDecompilation():
				raw = [("raw", 1)]
			else:
				raw = []
			if fdSelect is None:
				xmlWriter.begintag("CharString", [('name', name)] + raw)
			else:
				xmlWriter.begintag("CharString",
						[('name', name), ('fdSelect', fdSelect)] + raw)
			xmlWriter.newline()
			charStr.toXML(xmlWriter)
			xmlWriter.endtag("CharString")
			xmlWriter.newline()
			if not i % step and progress is not None:
				progress.setLabel("Dumping 'CFF ' table... (%s)" % name)
				progress.increment(step / float(numGlyphs))
			i = i + 1
	
	def fromXML(self, (name, attrs, content)):
		for element in content:
			if isinstance(element, StringType):
				continue
			name, attrs, content = element
			if name <> "CharString":
				continue
			glyphName = attrs["name"]
			if hasattr(self.private, "Subrs"):
				subrs = self.private.Subrs
			else:
				subrs = []
			globalSubrs = self.globalSubrs
			charString = psCharStrings.T2CharString(None, subrs=subrs, globalSubrs=globalSubrs)
			charString.fromXML((name, attrs, content))
			self[glyphName] = charString


def readCard8(file):
	return ord(file.read(1))

def readCard16(file):
	value, = struct.unpack(">H", file.read(2))
	return value

def writeCard8(file, value):
	file.write(chr(value))

def writeCard16(file, value):
	file.write(struct.pack(">H", value))

def packCard8(value):
	return chr(value)

def packCard16(value):
	return struct.pack(">H", value)

def buildOperatorDict(table):
	d = {}
	for op, name, arg, default, conv in table:
		d[op] = (name, arg)
	return d

def buildOpcodeDict(table):
	d = {}
	for op, name, arg, default, conv in table:
		if type(op) == TupleType:
			op = chr(op[0]) + chr(op[1])
		else:
			op = chr(op)
		d[name] = (op, arg)
	return d

def buildOrder(table):
	l = []
	for op, name, arg, default, conv in table:
		l.append(name)
	return l

def buildDefaults(table):
	d = {}
	for op, name, arg, default, conv in table:
		if default is not None:
			d[name] = default
	return d

def buildConverters(table):
	d = {}
	for op, name, arg, default, conv in table:
		d[name] = conv
	return d


class SimpleConverter:
	def read(self, parent, value):
		return value
	def write(self, parent, value):
		return value
	def xmlWrite(self, xmlWriter, name, value, progress):
		xmlWriter.simpletag(name, value=value)
		xmlWriter.newline()
	def xmlRead(self, (name, attrs, content), parent):
		return attrs["value"]

class Latin1Converter(SimpleConverter):
	def xmlRead(self, (name, attrs, content), parent):
		s = unicode(attrs["value"], "utf-8")
		return s.encode("latin-1")


def parseNum(s):
	try:
		value = int(s)
	except:
		value = float(s)
	return value

class NumberConverter(SimpleConverter):
	def xmlRead(self, (name, attrs, content), parent):
		return parseNum(attrs["value"])

class ArrayConverter(SimpleConverter):
	def xmlWrite(self, xmlWriter, name, value, progress):
		value = map(str, value)
		xmlWriter.simpletag(name, value=" ".join(value))
		xmlWriter.newline()
	def xmlRead(self, (name, attrs, content), parent):
		values = attrs["value"].split()
		return map(parseNum, values)

class TableConverter(SimpleConverter):
	def xmlWrite(self, xmlWriter, name, value, progress):
		xmlWriter.begintag(name)
		xmlWriter.newline()
		value.toXML(xmlWriter, progress)
		xmlWriter.endtag(name)
		xmlWriter.newline()
	def xmlRead(self, (name, attrs, content), parent):
		ob = self.getClass()()
		for element in content:
			if isinstance(element, StringType):
				continue
			ob.fromXML(element)
		return ob

class PrivateDictConverter(TableConverter):
	def getClass(self):
		return PrivateDict
	def read(self, parent, value):
		size, offset = value
		file = parent.file
		priv = PrivateDict(parent.strings, file, offset)
		file.seek(offset)
		data = file.read(size)
		len(data) == size
		priv.decompile(data)
		return priv
	def write(self, parent, value):
		return (0, 0)  # dummy value

class SubrsConverter(TableConverter):
	def getClass(self):
		return SubrsIndex
	def read(self, parent, value):
		file = parent.file
		file.seek(parent.offset + value)  # Offset(self)
		return SubrsIndex(file)
	def write(self, parent, value):
		return 0  # dummy value

class CharStringsConverter(TableConverter):
	def read(self, parent, value):
		file = parent.file
		charset = parent.charset
		globalSubrs = parent.GlobalSubrs
		if hasattr(parent, "ROS"):
			fdSelect, fdArray = parent.FDSelect, parent.FDArray
			private = None
		else:
			fdSelect, fdArray = None, None
			private = parent.Private
		file.seek(value)  # Offset(0)
		return CharStrings(file, charset, globalSubrs, private, fdSelect, fdArray)
	def write(self, parent, value):
		return 0  # dummy value
	def xmlRead(self, (name, attrs, content), parent):
		# XXX needs work for CID fonts
		fdSelect, fdArray = None, None
		charStrings = CharStrings(None, None, parent.GlobalSubrs, parent.Private, fdSelect, fdArray)
		charStrings.fromXML((name, attrs, content))
		return charStrings

class CharsetConverter:
	def read(self, parent, value):
		isCID = hasattr(parent, "ROS")
		if value > 2:
			numGlyphs = parent.numGlyphs
			file = parent.file
			file.seek(value)
			if DEBUG:
				print "loading charset at %s" % value
			format = readCard8(file)
			if format == 0:
				charset = parseCharset0(numGlyphs, file, parent.strings)
			elif format == 1 or format == 2:
				charset = parseCharset(numGlyphs, file, parent.strings, isCID, format)
			else:
				raise NotImplementedError
			assert len(charset) == numGlyphs
			if DEBUG:
				print "    charset end at %s" % file.tell()
		else:
			if isCID or not hasattr(parent, "CharStrings"):
				assert value == 0
				charset = None
			elif value == 0:
				charset = ISOAdobe
			elif value == 1:
				charset = Expert
			elif value == 2:
				charset = ExpertSubset
			# self.charset:
			#   0: ISOAdobe (or CID font!)
			#   1: Expert
			#   2: ExpertSubset
			charset = None  # 
		return charset
	def write(self, parent, value):
		return 0  # dummy value
	def xmlWrite(self, xmlWriter, name, value, progress):
		# XXX only write charset when not in OT/TTX context, where we
		# dump charset as a separate "GlyphOrder" table.
		##xmlWriter.simpletag("charset")
		xmlWriter.comment("charset is dumped separately as the 'GlyphOrder' element")
		xmlWriter.newline()
	def xmlRead(self, (name, attrs, content), parent):
		if 0:
			return safeEval(attrs["value"])


class CharsetCompiler:
	
	def __init__(self, strings, charset, parent):
		assert charset[0] == '.notdef'
		data0 = packCharset0(charset, strings)
		data = packCharset(charset, strings)
		if len(data) < len(data0):
			self.data = data
		else:
			self.data = data0
		self.parent = parent
	
	def setPos(self, pos, endPos):
		self.parent.rawDict["charset"] = pos
	
	def getDataLength(self):
		return len(self.data)
	
	def toFile(self, file):
		file.write(self.data)


def packCharset0(charset, strings):
	format = 0
	data = [packCard8(format)]
	for name in charset[1:]:
		data.append(packCard16(strings.getSID(name)))
	return "".join(data)

def packCharset(charset, strings):
	format = 1
	ranges = []
	first = None
	end = 0
	for name in charset[1:]:
		SID = strings.getSID(name)
		if first is None:
			first = SID
		elif end + 1 <> SID:
			nLeft = end - first
			if nLeft > 255:
				format = 2
			ranges.append((first, nLeft))
			first = SID
		end = SID
	nLeft = end - first
	if nLeft > 255:
		format = 2
	ranges.append((first, nLeft))
	
	data = [packCard8(format)]
	if format == 1:
		nLeftFunc = packCard8
	else:
		nLeftFunc = packCard16
	for first, nLeft in ranges:
		data.append(packCard16(first) + nLeftFunc(nLeft))
	return "".join(data)

def parseCharset0(numGlyphs, file, strings):
	charset = [".notdef"]
	for i in range(numGlyphs - 1):
		SID = readCard16(file)
		charset.append(strings[SID])
	return charset

def parseCharset(numGlyphs, file, strings, isCID, format):
	charset = ['.notdef']
	count = 1
	if format == 1:
		nLeftFunc = readCard8
	else:
		nLeftFunc = readCard16
	while count < numGlyphs:
		first = readCard16(file)
		nLeft = nLeftFunc(file)
		if isCID:
			for CID in range(first, first+nLeft+1):
				charset.append(CID)
		else:
			for SID in range(first, first+nLeft+1):
				charset.append(strings[SID])
		count = count + nLeft + 1
	return charset


class EncodingCompiler:

	def __init__(self, strings, encoding, parent):
		assert not isinstance(encoding, StringType)
		data0 = packEncoding0(parent.dictObj.charset, encoding, parent.strings)
		data1 = packEncoding1(parent.dictObj.charset, encoding, parent.strings)
		if len(data0) < len(data1):
			self.data = data0
		else:
			self.data = data1
		self.parent = parent

	def setPos(self, pos, endPos):
		self.parent.rawDict["Encoding"] = pos
	
	def getDataLength(self):
		return len(self.data)
	
	def toFile(self, file):
		file.write(self.data)


class EncodingConverter(SimpleConverter):

	def read(self, parent, value):
		if value == 0:
			return "StandardEncoding"
		elif value == 1:
			return "ExpertEncoding"
		else:
			assert value > 1
			file = parent.file
			file.seek(value)
			if DEBUG:
				print "loading Encoding at %s" % value
			format = readCard8(file)
			haveSupplement = format & 0x80
			if haveSupplement:
				raise NotImplementedError, "Encoding supplements are not yet supported"
			format = format & 0x7f
			if format == 0:
				encoding = parseEncoding0(parent.charset, file, haveSupplement,
						parent.strings)
			elif format == 1:
				encoding = parseEncoding1(parent.charset, file, haveSupplement,
						parent.strings)
			return encoding

	def write(self, parent, value):
		if value == "StandardEncoding":
			return 0
		elif value == "ExpertEncoding":
			return 1
		return 0  # dummy value

	def xmlWrite(self, xmlWriter, name, value, progress):
		if value in ("StandardEncoding", "ExpertEncoding"):
			xmlWriter.simpletag(name, name=value)
			xmlWriter.newline()
			return
		xmlWriter.begintag(name)
		xmlWriter.newline()
		for code in range(len(value)):
			glyphName = value[code]
			if glyphName != ".notdef":
				xmlWriter.simpletag("map", code=hex(code), name=glyphName)
				xmlWriter.newline()
		xmlWriter.endtag(name)
		xmlWriter.newline()

	def xmlRead(self, (name, attrs, content), parent):
		if attrs.has_key("name"):
			return attrs["name"]
		encoding = [".notdef"] * 256
		for element in content:
			if isinstance(element, StringType):
				continue
			name, attrs, content = element
			code = safeEval(attrs["code"])
			glyphName = attrs["name"]
			encoding[code] = glyphName
		return encoding


def parseEncoding0(charset, file, haveSupplement, strings):
	nCodes = readCard8(file)
	encoding = [".notdef"] * 256
	for glyphID in range(1, nCodes + 1):
		code = readCard8(file)
		if code != 0:
			encoding[code] = charset[glyphID]
	return encoding

def parseEncoding1(charset, file, haveSupplement, strings):
	nRanges = readCard8(file)
	encoding = [".notdef"] * 256
	glyphID = 1
	for i in range(nRanges):
		code = readCard8(file)
		nLeft = readCard8(file)
		for glyphID in range(glyphID, glyphID + nLeft + 1):
			encoding[code] = charset[glyphID]
			code = code + 1
		glyphID = glyphID + 1
	return encoding

def packEncoding0(charset, encoding, strings):
	format = 0
	m = {}
	for code in range(len(encoding)):
		name = encoding[code]
		if name != ".notdef":
			m[name] = code
	codes = []
	for name in charset[1:]:
		code = m.get(name)
		codes.append(code)
	
	while codes and codes[-1] is None:
		codes.pop()

	data = [packCard8(format), packCard8(len(codes))]
	for code in codes:
		if code is None:
			code = 0
		data.append(packCard8(code))
	return "".join(data)

def packEncoding1(charset, encoding, strings):
	format = 1
	m = {}
	for code in range(len(encoding)):
		name = encoding[code]
		if name != ".notdef":
			m[name] = code
	ranges = []
	first = None
	end = 0
	for name in charset[1:]:
		code = m.get(name, -1)
		if first is None:
			first = code
		elif end + 1 <> code:
			nLeft = end - first
			ranges.append((first, nLeft))
			first = code
		end = code
	nLeft = end - first
	ranges.append((first, nLeft))
	
	# remove unencoded glyphs at the end.
	while ranges and ranges[-1][0] == -1:
		ranges.pop()

	data = [packCard8(format), packCard8(len(ranges))]
	for first, nLeft in ranges:
		if first == -1:  # unencoded
			first = 0
		data.append(packCard8(first) + packCard8(nLeft))
	return "".join(data)


class FDArrayConverter(TableConverter):
	def read(self, parent, value):
		file = parent.file
		file.seek(value)
		fdArray = TopDictIndex(file)
		fdArray.strings = parent.strings
		fdArray.GlobalSubrs = parent.GlobalSubrs
		return fdArray


class FDSelectConverter:
	def read(self, parent, value):
		file = parent.file
		file.seek(value)
		format = readCard8(file)
		numGlyphs = parent.numGlyphs
		if format == 0:
			from array import array
			fdSelect = array("B", file.read(numGlyphs)).tolist()
		elif format == 3:
			fdSelect = [None] * numGlyphs
			nRanges = readCard16(file)
			prev = None
			for i in range(nRanges):
				first = readCard16(file)
				if prev is not None:
					for glyphID in range(prev, first):
						fdSelect[glyphID] = fd
				prev = first
				fd = readCard8(file)
			if prev is not None:
				first = readCard16(file)
				for glyphID in range(prev, first):
					fdSelect[glyphID] = fd
		else:
			assert 0, "unsupported FDSelect format: %s" % format
		return fdSelect
	def xmlWrite(self, xmlWriter, name, value, progress):
		pass


class ROSConverter(SimpleConverter):
	def xmlWrite(self, xmlWriter, name, value, progress):
		registry, order, supplement = value
		xmlWriter.simpletag(name, [('Registry', registry), ('Order', order),
			('Supplement', supplement)])
		xmlWriter.newline()


topDictOperators = [
#	opcode     name                  argument type   default    converter
	((12, 30), 'ROS',        ('SID','SID','number'), None,      ROSConverter()),
	((12, 20), 'SyntheticBase',      'number',       None,      None),
	(0,        'version',            'SID',          None,      None),
	(1,        'Notice',             'SID',          None,      Latin1Converter()),
	((12, 0),  'Copyright',          'SID',          None,      Latin1Converter()),
	(2,        'FullName',           'SID',          None,      None),
	((12, 38), 'FontName',           'SID',          None,      None),
	(3,        'FamilyName',         'SID',          None,      None),
	(4,        'Weight',             'SID',          None,      None),
	((12, 1),  'isFixedPitch',       'number',       0,         None),
	((12, 2),  'ItalicAngle',        'number',       0,         None),
	((12, 3),  'UnderlinePosition',  'number',       None,      None),
	((12, 4),  'UnderlineThickness', 'number',       50,        None),
	((12, 5),  'PaintType',          'number',       0,         None),
	((12, 6),  'CharstringType',     'number',       2,         None),
	((12, 7),  'FontMatrix',         'array',  [0.001,0,0,0.001,0,0],  None),
	(13,       'UniqueID',           'number',       None,      None),
	(5,        'FontBBox',           'array',  [0,0,0,0],       None),
	((12, 8),  'StrokeWidth',        'number',       0,         None),
	(14,       'XUID',               'array',        None,      None),
	(15,       'charset',            'number',       0,         CharsetConverter()),
	((12, 21), 'PostScript',         'SID',          None,      None),
	((12, 22), 'BaseFontName',       'SID',          None,      None),
	((12, 23), 'BaseFontBlend',      'delta',        None,      None),
	((12, 31), 'CIDFontVersion',     'number',       0,         None),
	((12, 32), 'CIDFontRevision',    'number',       0,         None),
	((12, 33), 'CIDFontType',        'number',       0,         None),
	((12, 34), 'CIDCount',           'number',       8720,      None),
	((12, 35), 'UIDBase',            'number',       None,      None),
	(16,       'Encoding',           'number',       0,         EncodingConverter()),
	((12, 36), 'FDArray',            'number',       None,      FDArrayConverter()),
	((12, 37), 'FDSelect',           'number',       None,      FDSelectConverter()),
	(18,       'Private',       ('number','number'), None,      PrivateDictConverter()),
	(17,       'CharStrings',        'number',       None,      CharStringsConverter()),
]

privateDictOperators = [
#	opcode     name                  argument type   default    converter
	(6,        'BlueValues',         'delta',        None,      None),
	(7,        'OtherBlues',         'delta',        None,      None),
	(8,        'FamilyBlues',        'delta',        None,      None),
	(9,        'FamilyOtherBlues',   'delta',        None,      None),
	((12, 9),  'BlueScale',          'number',       0.039625,  None),
	((12, 10), 'BlueShift',          'number',       7,         None),
	((12, 11), 'BlueFuzz',           'number',       1,         None),
	(10,       'StdHW',              'number',       None,      None),
	(11,       'StdVW',              'number',       None,      None),
	((12, 12), 'StemSnapH',          'delta',        None,      None),
	((12, 13), 'StemSnapV',          'delta',        None,      None),
	((12, 14), 'ForceBold',          'number',       0,         None),
	((12, 15), 'ForceBoldThreshold', 'number',       None,      None),  # deprecated
	((12, 16), 'lenIV',              'number',       None,      None),  # deprecated
	((12, 17), 'LanguageGroup',      'number',       0,         None),
	((12, 18), 'ExpansionFactor',    'number',       0.06,      None),
	((12, 19), 'initialRandomSeed',  'number',       0,         None),
	(20,       'defaultWidthX',      'number',       0,         None),
	(21,       'nominalWidthX',      'number',       0,         None),
	(19,       'Subrs',              'number',       None,      SubrsConverter()),
]

def addConverters(table):
	for i in range(len(table)):
		op, name, arg, default, conv = table[i]
		if conv is not None:
			continue
		if arg in ("delta", "array"):
			conv = ArrayConverter()
		elif arg == "number":
			conv = NumberConverter()
		elif arg == "SID":
			conv = SimpleConverter()
		else:
			assert 0
		table[i] = op, name, arg, default, conv

addConverters(privateDictOperators)
addConverters(topDictOperators)


class TopDictDecompiler(psCharStrings.DictDecompiler):
	operators = buildOperatorDict(topDictOperators)


class PrivateDictDecompiler(psCharStrings.DictDecompiler):
	operators = buildOperatorDict(privateDictOperators)


class DictCompiler:
	
	def __init__(self, dictObj, strings, parent):
		assert isinstance(strings, IndexedStrings)
		self.dictObj = dictObj
		self.strings = strings
		self.parent = parent
		rawDict = {}
		for name in dictObj.order:
			value = getattr(dictObj, name, None)
			if value is None:
				continue
			conv = dictObj.converters[name]
			value = conv.write(dictObj, value)
			if value == dictObj.defaults.get(name):
				continue
			rawDict[name] = value
		self.rawDict = rawDict
	
	def setPos(self, pos, endPos):
		pass
	
	def getDataLength(self):
		return len(self.compile("getDataLength"))
	
	def compile(self, reason):
		if DEBUG:
			print "-- compiling %s for %s" % (self.__class__.__name__, reason)
		rawDict = self.rawDict
		data = []
		for name in self.dictObj.order:
			value = rawDict.get(name)
			if value is None:
				continue
			op, argType = self.opcodes[name]
			if type(argType) == TupleType:
				l = len(argType)
				assert len(value) == l, "value doesn't match arg type"
				for i in range(l):
					arg = argType[l - i - 1]
					v = value[i]
					arghandler = getattr(self, "arg_" + arg)
					data.append(arghandler(v))
			else:
				arghandler = getattr(self, "arg_" + argType)
				data.append(arghandler(value))
			data.append(op)
		return "".join(data)
	
	def toFile(self, file):
		file.write(self.compile("toFile"))
	
	def arg_number(self, num):
		return encodeNumber(num)
	def arg_SID(self, s):
		return psCharStrings.encodeIntCFF(self.strings.getSID(s))
	def arg_array(self, value):
		data = []
		for num in value:
			data.append(encodeNumber(num))
		return "".join(data)
	def arg_delta(self, value):
		out = []
		last = 0
		for v in value:
			out.append(v - last)
			last = v
		data = []
		for num in out:
			data.append(encodeNumber(num))
		return "".join(data)


def encodeNumber(num):
	if type(num) == FloatType:
		return psCharStrings.encodeFloat(num)
	else:
		return psCharStrings.encodeIntCFF(num)


class TopDictCompiler(DictCompiler):
	
	opcodes = buildOpcodeDict(topDictOperators)
	
	def getChildren(self, strings):
		children = []
		if hasattr(self.dictObj, "charset"):
			children.append(CharsetCompiler(strings, self.dictObj.charset, self))
		if hasattr(self.dictObj, "Encoding"):
			encoding = self.dictObj.Encoding
			if not isinstance(encoding, StringType):
				children.append(EncodingCompiler(strings, encoding, self))
		if hasattr(self.dictObj, "CharStrings"):
			items = []
			charStrings = self.dictObj.CharStrings
			for name in self.dictObj.charset:
				items.append(charStrings[name])
			charStringsComp = CharStringsCompiler(items, strings, self)
			children.append(charStringsComp)
		if hasattr(self.dictObj, "Private"):
			privComp = self.dictObj.Private.getCompiler(strings, self)
			children.append(privComp)
			children.extend(privComp.getChildren(strings))
		return children


class PrivateDictCompiler(DictCompiler):
	
	opcodes = buildOpcodeDict(privateDictOperators)
	
	def setPos(self, pos, endPos):
		size = endPos - pos
		self.parent.rawDict["Private"] = size, pos
		self.pos = pos
	
	def getChildren(self, strings):
		children = []
		if hasattr(self.dictObj, "Subrs"):
			children.append(self.dictObj.Subrs.getCompiler(strings, self))
		return children


class BaseDict:
	
	def __init__(self, strings=None, file=None, offset=None):
		self.rawDict = {}
		if DEBUG:
			print "loading %s at %s" % (self.__class__.__name__, offset)
		self.file = file
		self.offset = offset
		self.strings = strings
		self.skipNames = []
	
	def decompile(self, data):
		if DEBUG:
			print "    length %s is %s" % (self.__class__.__name__, len(data))
		dec = self.decompilerClass(self.strings)
		dec.decompile(data)
		self.rawDict = dec.getDict()
		self.postDecompile()
	
	def postDecompile(self):
		pass
	
	def getCompiler(self, strings, parent):
		return self.compilerClass(self, strings, parent)
	
	def __getattr__(self, name):
		value = self.rawDict.get(name)
		if value is None:
			value = self.defaults.get(name)
		if value is None:
			raise AttributeError, name
		conv = self.converters[name]
		value = conv.read(self, value)
		setattr(self, name, value)
		return value
	
	def toXML(self, xmlWriter, progress):
		for name in self.order:
			if name in self.skipNames:
				continue
			value = getattr(self, name, None)
			if value is None:
				continue
			conv = self.converters[name]
			conv.xmlWrite(xmlWriter, name, value, progress)
	
	def fromXML(self, (name, attrs, content)):
		conv = self.converters[name]
		value = conv.xmlRead((name, attrs, content), self)
		setattr(self, name, value)


class TopDict(BaseDict):
	
	defaults = buildDefaults(topDictOperators)
	converters = buildConverters(topDictOperators)
	order = buildOrder(topDictOperators)
	decompilerClass = TopDictDecompiler
	compilerClass = TopDictCompiler
	
	def __init__(self, strings=None, file=None, offset=None, GlobalSubrs=None):
		BaseDict.__init__(self, strings, file, offset)
		self.GlobalSubrs = GlobalSubrs
	
	def getGlyphOrder(self):
		return self.charset
	
	def postDecompile(self):
		offset = self.rawDict.get("CharStrings")
		if offset is None:
			return
		# get the number of glyphs beforehand.
		self.file.seek(offset)
		self.numGlyphs = readCard16(self.file)
	
	def toXML(self, xmlWriter, progress):
		if hasattr(self, "CharStrings"):
			self.decompileAllCharStrings(progress)
		if not hasattr(self, "ROS") or not hasattr(self, "CharStrings"):
			# these values have default values, but I only want them to show up
			# in CID fonts.
			self.skipNames = ['CIDFontVersion', 'CIDFontRevision', 'CIDFontType',
					'CIDCount']
		BaseDict.toXML(self, xmlWriter, progress)
	
	def decompileAllCharStrings(self, progress):
		# XXX only when doing ttdump -i?
		i = 0
		for charString in self.CharStrings.values():
			charString.decompile()
			if not i % 30 and progress:
				progress.increment(0)  # update
			i = i + 1


class PrivateDict(BaseDict):
	defaults = buildDefaults(privateDictOperators)
	converters = buildConverters(privateDictOperators)
	order = buildOrder(privateDictOperators)
	decompilerClass = PrivateDictDecompiler
	compilerClass = PrivateDictCompiler


class IndexedStrings:
	
	"""SID -> string mapping."""
	
	def __init__(self, file=None):
		if file is None:
			strings = []
		else:
			strings = list(Index(file))
		self.strings = strings
	
	def getCompiler(self):
		return IndexedStringsCompiler(self, None, None)
	
	def __len__(self):
		return len(self.strings)
	
	def __getitem__(self, SID):
		if SID < cffStandardStringCount:
			return cffStandardStrings[SID]
		else:
			return self.strings[SID - cffStandardStringCount]
	
	def getSID(self, s):
		if not hasattr(self, "stringMapping"):
			self.buildStringMapping()
		if cffStandardStringMapping.has_key(s):
			SID = cffStandardStringMapping[s]
		elif self.stringMapping.has_key(s):
			SID = self.stringMapping[s]
		else:
			SID = len(self.strings) + cffStandardStringCount
			self.strings.append(s)
			self.stringMapping[s] = SID
		return SID
	
	def getStrings(self):
		return self.strings
	
	def buildStringMapping(self):
		self.stringMapping = {}
		for index in range(len(self.strings)):
			self.stringMapping[self.strings[index]] = index + cffStandardStringCount


# The 391 Standard Strings as used in the CFF format.
# from Adobe Technical None #5176, version 1.0, 18 March 1998

cffStandardStrings = ['.notdef', 'space', 'exclam', 'quotedbl', 'numbersign', 
		'dollar', 'percent', 'ampersand', 'quoteright', 'parenleft', 'parenright', 
		'asterisk', 'plus', 'comma', 'hyphen', 'period', 'slash', 'zero', 'one', 
		'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'colon', 
		'semicolon', 'less', 'equal', 'greater', 'question', 'at', 'A', 'B', 'C', 
		'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 
		'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z', 'bracketleft', 'backslash', 
		'bracketright', 'asciicircum', 'underscore', 'quoteleft', 'a', 'b', 'c', 
		'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm', 'n', 'o', 'p', 'q', 'r', 
		's', 't', 'u', 'v', 'w', 'x', 'y', 'z', 'braceleft', 'bar', 'braceright', 
		'asciitilde', 'exclamdown', 'cent', 'sterling', 'fraction', 'yen', 'florin', 
		'section', 'currency', 'quotesingle', 'quotedblleft', 'guillemotleft', 
		'guilsinglleft', 'guilsinglright', 'fi', 'fl', 'endash', 'dagger', 
		'daggerdbl', 'periodcentered', 'paragraph', 'bullet', 'quotesinglbase', 
		'quotedblbase', 'quotedblright', 'guillemotright', 'ellipsis', 'perthousand', 
		'questiondown', 'grave', 'acute', 'circumflex', 'tilde', 'macron', 'breve', 
		'dotaccent', 'dieresis', 'ring', 'cedilla', 'hungarumlaut', 'ogonek', 'caron', 
		'emdash', 'AE', 'ordfeminine', 'Lslash', 'Oslash', 'OE', 'ordmasculine', 'ae', 
		'dotlessi', 'lslash', 'oslash', 'oe', 'germandbls', 'onesuperior', 
		'logicalnot', 'mu', 'trademark', 'Eth', 'onehalf', 'plusminus', 'Thorn', 
		'onequarter', 'divide', 'brokenbar', 'degree', 'thorn', 'threequarters', 
		'twosuperior', 'registered', 'minus', 'eth', 'multiply', 'threesuperior', 
		'copyright', 'Aacute', 'Acircumflex', 'Adieresis', 'Agrave', 'Aring', 
		'Atilde', 'Ccedilla', 'Eacute', 'Ecircumflex', 'Edieresis', 'Egrave', 
		'Iacute', 'Icircumflex', 'Idieresis', 'Igrave', 'Ntilde', 'Oacute', 
		'Ocircumflex', 'Odieresis', 'Ograve', 'Otilde', 'Scaron', 'Uacute', 
		'Ucircumflex', 'Udieresis', 'Ugrave', 'Yacute', 'Ydieresis', 'Zcaron', 
		'aacute', 'acircumflex', 'adieresis', 'agrave', 'aring', 'atilde', 'ccedilla', 
		'eacute', 'ecircumflex', 'edieresis', 'egrave', 'iacute', 'icircumflex', 
		'idieresis', 'igrave', 'ntilde', 'oacute', 'ocircumflex', 'odieresis', 
		'ograve', 'otilde', 'scaron', 'uacute', 'ucircumflex', 'udieresis', 'ugrave', 
		'yacute', 'ydieresis', 'zcaron', 'exclamsmall', 'Hungarumlautsmall', 
		'dollaroldstyle', 'dollarsuperior', 'ampersandsmall', 'Acutesmall', 
		'parenleftsuperior', 'parenrightsuperior', 'twodotenleader', 'onedotenleader', 
		'zerooldstyle', 'oneoldstyle', 'twooldstyle', 'threeoldstyle', 'fouroldstyle', 
		'fiveoldstyle', 'sixoldstyle', 'sevenoldstyle', 'eightoldstyle', 
		'nineoldstyle', 'commasuperior', 'threequartersemdash', 'periodsuperior', 
		'questionsmall', 'asuperior', 'bsuperior', 'centsuperior', 'dsuperior', 
		'esuperior', 'isuperior', 'lsuperior', 'msuperior', 'nsuperior', 'osuperior', 
		'rsuperior', 'ssuperior', 'tsuperior', 'ff', 'ffi', 'ffl', 'parenleftinferior', 
		'parenrightinferior', 'Circumflexsmall', 'hyphensuperior', 'Gravesmall', 
		'Asmall', 'Bsmall', 'Csmall', 'Dsmall', 'Esmall', 'Fsmall', 'Gsmall', 'Hsmall', 
		'Ismall', 'Jsmall', 'Ksmall', 'Lsmall', 'Msmall', 'Nsmall', 'Osmall', 'Psmall', 
		'Qsmall', 'Rsmall', 'Ssmall', 'Tsmall', 'Usmall', 'Vsmall', 'Wsmall', 'Xsmall', 
		'Ysmall', 'Zsmall', 'colonmonetary', 'onefitted', 'rupiah', 'Tildesmall', 
		'exclamdownsmall', 'centoldstyle', 'Lslashsmall', 'Scaronsmall', 'Zcaronsmall', 
		'Dieresissmall', 'Brevesmall', 'Caronsmall', 'Dotaccentsmall', 'Macronsmall', 
		'figuredash', 'hypheninferior', 'Ogoneksmall', 'Ringsmall', 'Cedillasmall', 
		'questiondownsmall', 'oneeighth', 'threeeighths', 'fiveeighths', 'seveneighths', 
		'onethird', 'twothirds', 'zerosuperior', 'foursuperior', 'fivesuperior', 
		'sixsuperior', 'sevensuperior', 'eightsuperior', 'ninesuperior', 'zeroinferior', 
		'oneinferior', 'twoinferior', 'threeinferior', 'fourinferior', 'fiveinferior', 
		'sixinferior', 'seveninferior', 'eightinferior', 'nineinferior', 'centinferior', 
		'dollarinferior', 'periodinferior', 'commainferior', 'Agravesmall', 
		'Aacutesmall', 'Acircumflexsmall', 'Atildesmall', 'Adieresissmall', 'Aringsmall', 
		'AEsmall', 'Ccedillasmall', 'Egravesmall', 'Eacutesmall', 'Ecircumflexsmall', 
		'Edieresissmall', 'Igravesmall', 'Iacutesmall', 'Icircumflexsmall', 
		'Idieresissmall', 'Ethsmall', 'Ntildesmall', 'Ogravesmall', 'Oacutesmall', 
		'Ocircumflexsmall', 'Otildesmall', 'Odieresissmall', 'OEsmall', 'Oslashsmall', 
		'Ugravesmall', 'Uacutesmall', 'Ucircumflexsmall', 'Udieresissmall', 
		'Yacutesmall', 'Thornsmall', 'Ydieresissmall', '001.000', '001.001', '001.002', 
		'001.003', 'Black', 'Bold', 'Book', 'Light', 'Medium', 'Regular', 'Roman', 
		'Semibold'
]

cffStandardStringCount = 391
assert len(cffStandardStrings) == cffStandardStringCount
# build reverse mapping
cffStandardStringMapping = {}
for _i in range(cffStandardStringCount):
	cffStandardStringMapping[cffStandardStrings[_i]] = _i

