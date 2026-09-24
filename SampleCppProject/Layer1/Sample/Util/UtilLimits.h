#pragma once

// Orphan header: there is deliberately NO UtilLimits.cpp. It sits in the Util component
// and is used by Util.cpp AND by Core.cpp (another component).
// An orphan header is listed ONCE, in one owner unit: the first unit by name in the
// header's OWN component that uses it. That is Util -- even though Core comes first by
// name, Core is not in this header's component.

#define UTIL_LIMIT (32)
#define UTIL_LIMIT_UNUSED (1)   // used by nobody, so listed nowhere

enum UtilMode {
    UTIL_MODE_FAST = 0,
    UTIL_MODE_SAFE = 1
};
