#pragma once

// Orphan header: there is deliberately NO LibLimits.cpp. It sits in the Lib component,
// but Lib.cpp never uses it -- only Core.cpp and Util.cpp do.
// With no user in its own component, it is listed in the first using unit by name
// anywhere: Core.

#define LIB_LIMIT (64)
