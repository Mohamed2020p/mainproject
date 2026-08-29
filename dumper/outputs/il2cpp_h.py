"""
``il2cpp.h`` - runtime structures and constants for the analysed build.

Drop this next to ``libil2cpp.so`` in IDA / Ghidra and the runtime objects
(``Il2CppClass``, ``MethodInfo``, ``Il2CppType`` ...) get proper shapes, plus
every ECMA-335 attribute mask needed to decode the flags you meet in a dump.
"""

from __future__ import annotations

from .. import consts
from ..executor import Executor

GENERIC_HEADER = r"""#pragma once

#include <stdint.h>

typedef void(*Il2CppMethodPointer)();

struct MethodInfo;
struct Il2CppClass;

struct VirtualInvokeData
{
    Il2CppMethodPointer methodPtr;
    const MethodInfo* method;
};

struct Il2CppType
{
    void* data;
    unsigned int bits;
};

struct Il2CppObject
{
    Il2CppClass* klass;
    void* monitor;
};

union Il2CppRGCTXData
{
    void* rgctxDataDummy;
    const MethodInfo* method;
    const Il2CppType* type;
    Il2CppClass* klass;
};

struct Il2CppRuntimeInterfaceOffsetPair
{
    Il2CppClass* interfaceType;
    int32_t offset;
};

struct Il2CppGenericInst
{
    uint32_t type_argc;
    const Il2CppType** type_argv;
};

struct Il2CppGenericContext
{
    const Il2CppGenericInst* class_inst;
    const Il2CppGenericInst* method_inst;
};

struct Il2CppGenericMethod
{
    const MethodInfo* methodDefinition;
    Il2CppGenericContext context;
};

struct ParameterInfo
{
    const char* name;
    int32_t position;
    uint32_t token;
    const Il2CppType* parameter_type;
};

struct MethodInfo
{
    Il2CppMethodPointer methodPointer;
    void* invoker_method;
    const char* name;
    Il2CppClass* klass;
    const Il2CppType* return_type;
    const ParameterInfo* parameters;
    union
    {
        const Il2CppRGCTXData* rgctx_data;
        const void* methodMetadataHandle;
    };
    union
    {
        const Il2CppGenericMethod* genericMethod;
        const void* genericContainerHandle;
    };
    uint32_t token;
    uint16_t flags;
    uint16_t iflags;
    uint16_t slot;
    uint16_t parameters_count;
    uint8_t bitfield;
};
"""

CLASS_V29 = r"""
struct Il2CppClass_1
{
    void* image;
    void* gc_desc;
    const char* name;
    const char* namespaze;
    Il2CppType byval_arg;
    Il2CppType this_arg;
    Il2CppClass* element_class;
    Il2CppClass* castClass;
    Il2CppClass* declaringType;
    Il2CppClass* parent;
    void* generic_class;
    void* typeMetadataHandle;
    void* interopData;
    Il2CppClass* klass;
    void* fields;
    void* events;
    void* properties;
    void* methods;
    Il2CppClass** nestedTypes;
    Il2CppClass** implementedInterfaces;
    void* interfaceOffsets;
};

struct Il2CppClass_2
{
    uint32_t token;
    uint16_t method_count;
    uint16_t property_count;
    uint16_t field_count;
    uint16_t event_count;
    uint16_t nested_type_count;
    uint16_t vtable_count;
    uint16_t interfaces_count;
    uint16_t interface_offsets_count;
    uint8_t typeHierarchyDepth;
    uint8_t genericRecursionDepth;
    uint8_t rank;
    uint8_t minimumAlignment;
    uint8_t naturalAligment;
    uint8_t packingSize;
    uint8_t bitfield_1;
    uint8_t bitfield_2;
};

struct Il2CppClass
{
    struct Il2CppClass_1 c1;
    void* unity_user_data;
    void* cctor_started;
    void* cctor_finished;
    void* cctor_thread;
    void* genericContainerHandle;
    struct Il2CppClass_2 c2;
    VirtualInvokeData vtable[0];
};
"""

CLASS_LEGACY = r"""
struct Il2CppClass
{
    void* image;
    void* gc_desc;
    const char* name;
    const char* namespaze;
    Il2CppType byval_arg;
    Il2CppType this_arg;
    Il2CppClass* element_class;
    Il2CppClass* castClass;
    Il2CppClass* declaringType;
    Il2CppClass* parent;
    void* generic_class;
    void* typeDefinition;
    void* interopData;
    Il2CppClass* klass;
    void* fields;
    void* events;
    void* properties;
    void* methods;
    Il2CppClass** nestedTypes;
    Il2CppClass** implementedInterfaces;
    void* interfaceOffsets;
    void* static_fields;
    const Il2CppRGCTXData* rgctx_data;
    Il2CppClass** typeHierarchy;
    void* unity_user_data;
    uint32_t cctor_started;
    uint32_t cctor_finished;
    uint64_t cctor_thread;
    int32_t genericContainerIndex;
    uint32_t token;
    uint16_t flags;
    uint16_t iflags;
    uint16_t slot;
    uint16_t method_count;
    uint16_t property_count;
    uint16_t field_count;
    uint16_t event_count;
    uint16_t nested_type_count;
    uint16_t vtable_count;
    uint16_t interfaces_count;
    uint16_t interface_offsets_count;
    uint8_t typeHierarchyDepth;
    uint8_t genericRecursionDepth;
    uint8_t rank;
    uint8_t minimumAlignment;
    uint8_t packingSize;
    uint8_t bitfield_1;
    uint8_t bitfield_2;
    VirtualInvokeData vtable[0];
};
"""

ENUM_HEADER = r"""
/* ---- Il2CppTypeEnum ---- */
enum Il2CppTypeEnum
{
    IL2CPP_TYPE_END = 0x00,
    IL2CPP_TYPE_VOID = 0x01,
    IL2CPP_TYPE_BOOLEAN = 0x02,
    IL2CPP_TYPE_CHAR = 0x03,
    IL2CPP_TYPE_I1 = 0x04,
    IL2CPP_TYPE_U1 = 0x05,
    IL2CPP_TYPE_I2 = 0x06,
    IL2CPP_TYPE_U2 = 0x07,
    IL2CPP_TYPE_I4 = 0x08,
    IL2CPP_TYPE_U4 = 0x09,
    IL2CPP_TYPE_I8 = 0x0a,
    IL2CPP_TYPE_U8 = 0x0b,
    IL2CPP_TYPE_R4 = 0x0c,
    IL2CPP_TYPE_R8 = 0x0d,
    IL2CPP_TYPE_STRING = 0x0e,
    IL2CPP_TYPE_PTR = 0x0f,
    IL2CPP_TYPE_BYREF = 0x10,
    IL2CPP_TYPE_VALUETYPE = 0x11,
    IL2CPP_TYPE_CLASS = 0x12,
    IL2CPP_TYPE_VAR = 0x13,
    IL2CPP_TYPE_ARRAY = 0x14,
    IL2CPP_TYPE_GENERICINST = 0x15,
    IL2CPP_TYPE_TYPEDBYREF = 0x16,
    IL2CPP_TYPE_I = 0x18,
    IL2CPP_TYPE_U = 0x19,
    IL2CPP_TYPE_FNPTR = 0x1b,
    IL2CPP_TYPE_OBJECT = 0x1c,
    IL2CPP_TYPE_SZARRAY = 0x1d,
    IL2CPP_TYPE_MVAR = 0x1e,
    IL2CPP_TYPE_CMOD_REQD = 0x1f,
    IL2CPP_TYPE_CMOD_OPT = 0x20,
    IL2CPP_TYPE_INTERNAL = 0x21,
    IL2CPP_TYPE_MODIFIER = 0x40,
    IL2CPP_TYPE_SENTINEL = 0x41,
    IL2CPP_TYPE_PINNED = 0x45,
    IL2CPP_TYPE_ENUM = 0x55
};

enum Il2CppMetadataUsage
{
    kIl2CppMetadataUsageInvalid = 0,
    kIl2CppMetadataUsageTypeInfo = 1,
    kIl2CppMetadataUsageIl2CppType = 2,
    kIl2CppMetadataUsageMethodDef = 3,
    kIl2CppMetadataUsageFieldInfo = 4,
    kIl2CppMetadataUsageStringLiteral = 5,
    kIl2CppMetadataUsageMethodRef = 6
};

/* ---- Field Attributes (ECMA-335 II.23.1.5) ---- */
#define FIELD_ATTRIBUTE_FIELD_ACCESS_MASK     0x0007
#define FIELD_ATTRIBUTE_COMPILER_CONTROLLED   0x0000
#define FIELD_ATTRIBUTE_PRIVATE               0x0001
#define FIELD_ATTRIBUTE_FAM_AND_ASSEM         0x0002
#define FIELD_ATTRIBUTE_ASSEMBLY              0x0003
#define FIELD_ATTRIBUTE_FAMILY                0x0004
#define FIELD_ATTRIBUTE_FAM_OR_ASSEM          0x0005
#define FIELD_ATTRIBUTE_PUBLIC                0x0006
#define FIELD_ATTRIBUTE_STATIC                0x0010
#define FIELD_ATTRIBUTE_INIT_ONLY             0x0020
#define FIELD_ATTRIBUTE_LITERAL               0x0040

/* ---- Method Attributes (ECMA-335 II.23.1.10) ---- */
#define METHOD_ATTRIBUTE_MEMBER_ACCESS_MASK   0x0007
#define METHOD_ATTRIBUTE_COMPILER_CONTROLLED  0x0000
#define METHOD_ATTRIBUTE_PRIVATE              0x0001
#define METHOD_ATTRIBUTE_FAM_AND_ASSEM        0x0002
#define METHOD_ATTRIBUTE_ASSEM                0x0003
#define METHOD_ATTRIBUTE_FAMILY               0x0004
#define METHOD_ATTRIBUTE_FAM_OR_ASSEM         0x0005
#define METHOD_ATTRIBUTE_PUBLIC               0x0006
#define METHOD_ATTRIBUTE_STATIC               0x0010
#define METHOD_ATTRIBUTE_FINAL                0x0020
#define METHOD_ATTRIBUTE_VIRTUAL              0x0040
#define METHOD_ATTRIBUTE_VTABLE_LAYOUT_MASK   0x0100
#define METHOD_ATTRIBUTE_REUSE_SLOT           0x0000
#define METHOD_ATTRIBUTE_NEW_SLOT             0x0100
#define METHOD_ATTRIBUTE_ABSTRACT             0x0400
#define METHOD_ATTRIBUTE_PINVOKE_IMPL         0x2000

/* ---- Type Attributes (ECMA-335 II.23.1.15) ---- */
#define TYPE_ATTRIBUTE_VISIBILITY_MASK        0x00000007
#define TYPE_ATTRIBUTE_NOT_PUBLIC             0x00000000
#define TYPE_ATTRIBUTE_PUBLIC                 0x00000001
#define TYPE_ATTRIBUTE_NESTED_PUBLIC          0x00000002
#define TYPE_ATTRIBUTE_NESTED_PRIVATE         0x00000003
#define TYPE_ATTRIBUTE_NESTED_FAMILY          0x00000004
#define TYPE_ATTRIBUTE_NESTED_ASSEMBLY        0x00000005
#define TYPE_ATTRIBUTE_NESTED_FAM_AND_ASSEM   0x00000006
#define TYPE_ATTRIBUTE_NESTED_FAM_OR_ASSEM    0x00000007
#define TYPE_ATTRIBUTE_INTERFACE              0x00000020
#define TYPE_ATTRIBUTE_ABSTRACT               0x00000080
#define TYPE_ATTRIBUTE_SEALED                 0x00000100
#define TYPE_ATTRIBUTE_SERIALIZABLE           0x00002000

/* ---- Param Attributes (ECMA-335 II.23.1.12) ---- */
#define PARAM_ATTRIBUTE_IN                    0x0001
#define PARAM_ATTRIBUTE_OUT                   0x0002
#define PARAM_ATTRIBUTE_OPTIONAL              0x0010
"""


def write_il2cpp_header(executor: Executor, path: str) -> None:
    metadata = executor.metadata
    il2cpp = executor.il2cpp

    parts = [
        "/*\n",
        " * il2cpp.h - generated by IL2CPP Dumper Studio\n",
        " * Developer  : Mohamed Annati\n",
        " * Metadata   : version %s\n" % metadata.version,
    ]
    if il2cpp is not None:
        parts.append(" * Binary     : %s (%d-bit)\n"
                     % (il2cpp.format_name, 32 if il2cpp.is32bit else 64))
        if il2cpp.code_registration:
            parts.append(" * CodeRegistration     : 0x%X\n" % il2cpp.code_registration)
        if il2cpp.metadata_registration:
            parts.append(" * MetadataRegistration : 0x%X\n" % il2cpp.metadata_registration)
    parts.append(" */\n")
    parts.append(GENERIC_HEADER)
    parts.append(CLASS_V29 if metadata.version >= 29 else CLASS_LEGACY)
    parts.append(ENUM_HEADER)

    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("".join(parts))
