#pragma once

// Orphan shared header: there is deliberately NO SharedDefs.cpp.
// Its macros/enum are #included and used by several Sample units. Each using
// unit's header table should list ONLY the symbols that unit actually uses.

typedef unsigned char UINT8;

#define SHARED_MAX_ITEMS 256
#define SHARED_MIN_ITEMS 4
#define SHARED_SCALE_FACTOR 8

// Enum with explicit underlying type (mirrors the "enum : UINT8" office case).
enum SharedLevel : UINT8 {
    LEVEL_LOW  = 0,
    LEVEL_MID  = 1,
    LEVEL_HIGH = 2
};
