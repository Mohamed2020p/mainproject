"""
IL2CPP / ECMA-335 constants.

Values mirror the CLI specification partitions II.21-22 and the constants used
by libil2cpp itself.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Sanity / detection
# ---------------------------------------------------------------------------

METADATA_SANITY = 0xFAB11BAF
MIN_METADATA_VERSION = 16
MAX_METADATA_VERSION = 31

# ---------------------------------------------------------------------------
# Il2CppTypeEnum
# ---------------------------------------------------------------------------

TYPE_END = 0x00
TYPE_VOID = 0x01
TYPE_BOOLEAN = 0x02
TYPE_CHAR = 0x03
TYPE_I1 = 0x04
TYPE_U1 = 0x05
TYPE_I2 = 0x06
TYPE_U2 = 0x07
TYPE_I4 = 0x08
TYPE_U4 = 0x09
TYPE_I8 = 0x0A
TYPE_U8 = 0x0B
TYPE_R4 = 0x0C
TYPE_R8 = 0x0D
TYPE_STRING = 0x0E
TYPE_PTR = 0x0F
TYPE_BYREF = 0x10
TYPE_VALUETYPE = 0x11
TYPE_CLASS = 0x12
TYPE_VAR = 0x13
TYPE_ARRAY = 0x14
TYPE_GENERICINST = 0x15
TYPE_TYPEDBYREF = 0x16
TYPE_I = 0x18
TYPE_U = 0x19
TYPE_FNPTR = 0x1B
TYPE_OBJECT = 0x1C
TYPE_SZARRAY = 0x1D
TYPE_MVAR = 0x1E
TYPE_CMOD_REQD = 0x1F
TYPE_CMOD_OPT = 0x20
TYPE_INTERNAL = 0x21
TYPE_MODIFIER = 0x40
TYPE_SENTINEL = 0x41
TYPE_PINNED = 0x45
TYPE_ENUM = 0x55
TYPE_IL2CPP_TYPE_INDEX = 0xFF

TYPE_ENUM_NAMES = {
    TYPE_END: "END", TYPE_VOID: "VOID", TYPE_BOOLEAN: "BOOLEAN",
    TYPE_CHAR: "CHAR", TYPE_I1: "I1", TYPE_U1: "U1", TYPE_I2: "I2",
    TYPE_U2: "U2", TYPE_I4: "I4", TYPE_U4: "U4", TYPE_I8: "I8",
    TYPE_U8: "U8", TYPE_R4: "R4", TYPE_R8: "R8", TYPE_STRING: "STRING",
    TYPE_PTR: "PTR", TYPE_BYREF: "BYREF", TYPE_VALUETYPE: "VALUETYPE",
    TYPE_CLASS: "CLASS", TYPE_VAR: "VAR", TYPE_ARRAY: "ARRAY",
    TYPE_GENERICINST: "GENERICINST", TYPE_TYPEDBYREF: "TYPEDBYREF",
    TYPE_I: "I", TYPE_U: "U", TYPE_FNPTR: "FNPTR", TYPE_OBJECT: "OBJECT",
    TYPE_SZARRAY: "SZARRAY", TYPE_MVAR: "MVAR", TYPE_CMOD_REQD: "CMOD_REQD",
    TYPE_CMOD_OPT: "CMOD_OPT", TYPE_INTERNAL: "INTERNAL",
    TYPE_ENUM: "ENUM", TYPE_IL2CPP_TYPE_INDEX: "IL2CPP_TYPE_INDEX",
}

# Il2CppTypeEnum -> C# keyword used in dump.cs
TYPE_KEYWORDS = {
    1: "void",
    2: "bool",
    3: "char",
    4: "sbyte",
    5: "byte",
    6: "short",
    7: "ushort",
    8: "int",
    9: "uint",
    10: "long",
    11: "ulong",
    12: "float",
    13: "double",
    14: "string",
    22: "TypedReference",
    24: "IntPtr",
    25: "UIntPtr",
    28: "object",
}

# ---------------------------------------------------------------------------
# Field attributes (ECMA-335 II.23.1.5)
# ---------------------------------------------------------------------------

FIELD_ATTRIBUTE_FIELD_ACCESS_MASK = 0x0007
FIELD_ATTRIBUTE_COMPILER_CONTROLLED = 0x0000
FIELD_ATTRIBUTE_PRIVATE = 0x0001
FIELD_ATTRIBUTE_FAM_AND_ASSEM = 0x0002
FIELD_ATTRIBUTE_ASSEMBLY = 0x0003
FIELD_ATTRIBUTE_FAMILY = 0x0004
FIELD_ATTRIBUTE_FAM_OR_ASSEM = 0x0005
FIELD_ATTRIBUTE_PUBLIC = 0x0006

FIELD_ATTRIBUTE_STATIC = 0x0010
FIELD_ATTRIBUTE_INIT_ONLY = 0x0020
FIELD_ATTRIBUTE_LITERAL = 0x0040
FIELD_ATTRIBUTE_NOT_SERIALIZED = 0x0080
FIELD_ATTRIBUTE_SPECIAL_NAME = 0x0200
FIELD_ATTRIBUTE_PINVOKE_IMPL = 0x2000

# ---------------------------------------------------------------------------
# Method attributes (ECMA-335 II.23.1.10)
# ---------------------------------------------------------------------------

METHOD_ATTRIBUTE_MEMBER_ACCESS_MASK = 0x0007
METHOD_ATTRIBUTE_COMPILER_CONTROLLED = 0x0000
METHOD_ATTRIBUTE_PRIVATE = 0x0001
METHOD_ATTRIBUTE_FAM_AND_ASSEM = 0x0002
METHOD_ATTRIBUTE_ASSEM = 0x0003
METHOD_ATTRIBUTE_FAMILY = 0x0004
METHOD_ATTRIBUTE_FAM_OR_ASSEM = 0x0005
METHOD_ATTRIBUTE_PUBLIC = 0x0006

METHOD_ATTRIBUTE_STATIC = 0x0010
METHOD_ATTRIBUTE_FINAL = 0x0020
METHOD_ATTRIBUTE_VIRTUAL = 0x0040
METHOD_ATTRIBUTE_HIDE_BY_SIG = 0x0080

METHOD_ATTRIBUTE_VTABLE_LAYOUT_MASK = 0x0100
METHOD_ATTRIBUTE_REUSE_SLOT = 0x0000
METHOD_ATTRIBUTE_NEW_SLOT = 0x0100

METHOD_ATTRIBUTE_ABSTRACT = 0x0400
METHOD_ATTRIBUTE_SPECIAL_NAME = 0x0800
METHOD_ATTRIBUTE_PINVOKE_IMPL = 0x2000

# ---------------------------------------------------------------------------
# Type attributes (ECMA-335 II.23.1.15)
# ---------------------------------------------------------------------------

TYPE_ATTRIBUTE_VISIBILITY_MASK = 0x00000007
TYPE_ATTRIBUTE_NOT_PUBLIC = 0x00000000
TYPE_ATTRIBUTE_PUBLIC = 0x00000001
TYPE_ATTRIBUTE_NESTED_PUBLIC = 0x00000002
TYPE_ATTRIBUTE_NESTED_PRIVATE = 0x00000003
TYPE_ATTRIBUTE_NESTED_FAMILY = 0x00000004
TYPE_ATTRIBUTE_NESTED_ASSEMBLY = 0x00000005
TYPE_ATTRIBUTE_NESTED_FAM_AND_ASSEM = 0x00000006
TYPE_ATTRIBUTE_NESTED_FAM_OR_ASSEM = 0x00000007

TYPE_ATTRIBUTE_INTERFACE = 0x00000020
TYPE_ATTRIBUTE_ABSTRACT = 0x00000080
TYPE_ATTRIBUTE_SEALED = 0x00000100
TYPE_ATTRIBUTE_SPECIAL_NAME = 0x00000400
TYPE_ATTRIBUTE_SERIALIZABLE = 0x00002000

# ---------------------------------------------------------------------------
# Parameter attributes (ECMA-335 II.23.1.12)
# ---------------------------------------------------------------------------

PARAM_ATTRIBUTE_IN = 0x0001
PARAM_ATTRIBUTE_OUT = 0x0002
PARAM_ATTRIBUTE_OPTIONAL = 0x0010

# ---------------------------------------------------------------------------
# ELF
# ---------------------------------------------------------------------------

EM_386 = 3
EM_ARM = 40
EM_X86_64 = 62
EM_AARCH64 = 183

PT_LOAD = 1
PT_DYNAMIC = 2

PF_X = 1
PF_W = 2
PF_R = 4

DT_NULL = 0
DT_NEEDED = 1
DT_PLTGOT = 3
DT_HASH = 4
DT_STRTAB = 5
DT_SYMTAB = 6
DT_RELA = 7
DT_RELASZ = 8
DT_RELAENT = 9
DT_STRSZ = 10
DT_SYMENT = 11
DT_INIT = 12
DT_FINI = 13
DT_REL = 17
DT_RELSZ = 18
DT_RELENT = 19
DT_INIT_ARRAY = 25
DT_FINI_ARRAY = 26
DT_GNU_HASH = 0x6FFFFEF5

R_ARM_ABS32 = 2
R_ARM_RELATIVE = 23
R_386_32 = 1
R_386_RELATIVE = 8
R_X86_64_64 = 1
R_X86_64_RELATIVE = 8
R_AARCH64_ABS64 = 257
R_AARCH64_RELATIVE = 1027

# ---------------------------------------------------------------------------
# File magic
# ---------------------------------------------------------------------------

MAGIC_ELF = b"\x7fELF"
MAGIC_PE = b"MZ"
MAGIC_MACHO_32 = b"\xcf\xfa\xed\xfe"
MAGIC_MACHO_64 = b"\xfe\xed\xfa\xcf"
MAGIC_MACHO_32_SWAP = b"\xce\xfa\xed\xfe"
MAGIC_MACHO_64_SWAP = b"\xcf\xfa\xed\xfe"
MAGIC_FAT = b"\xca\xfe\xba\xbe"
MAGIC_NSO = b"NSO0"
MAGIC_WASM = b"\x00asm"
MAGIC_ZIP = b"PK\x03\x04"
