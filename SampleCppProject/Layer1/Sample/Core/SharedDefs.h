#pragma once

// Orphan shared header: there is deliberately NO SharedDefs.cpp.
// Its macros/enum are #included and used by several Sample units (Core, Lib, Util).
// It is listed ONCE, by Core: the first user in its own component. Core's table lists
// every symbol here that any unit uses (SHARED_SCALE_FACTOR for Lib, SHARED_BUFSZ for
// Util); Lib and Util list none of it. A symbol nobody uses is listed nowhere.

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
// listed with the rest of this header, by its owner. Defined once in Core.cpp; Lib reads
// it without declaring it; Util includes this header and never touches it (included is
// not use). In Core the definition `int g_sharedTick = 0;` wins over this `extern`.
extern int g_sharedTick;

// Enum with explicit underlying type (mirrors the "enum : UINT8" office case).
enum SharedLevel : UINT8 {
    LEVEL_LOW  = 0,
    LEVEL_MID  = 1,
    LEVEL_HIGH = 2
};
