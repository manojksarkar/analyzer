#pragma once

// Orphan shared header: there is deliberately NO SharedDefs.cpp.
// Its macros/enum are #included and used by several Sample units. Each using
// unit's header table should list ONLY the symbols that unit actually uses.

typedef unsigned char UINT8;

#define SHARED_MAX_ITEMS 256
#define SHARED_MIN_ITEMS 4
#define SHARED_SCALE_FACTOR 8
#define SHARED_BUFSZ (6)
#define SHARED_MASK ((1 << 0) | \
                     (1 << 1) | \
                     (1 << 2))

// A GLOBAL declared in an orphan header. It belongs to no unit, so it appeared in NO
// header table at all -- while the flowcharts of the units reading it named it. It is
// now lent to each unit whose functions touch it, the same way the macros above are.
// Defined once in Core.cpp; Lib reads it without declaring it; Util includes this header
// and never touches it, so Util must get no row for it (included is not enough).
extern int g_sharedTick;

// Enum with explicit underlying type (mirrors the "enum : UINT8" office case).
enum SharedLevel : UINT8 {
    LEVEL_LOW  = 0,
    LEVEL_MID  = 1,
    LEVEL_HIGH = 2
};
