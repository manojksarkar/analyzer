#pragma once

// Fixture for 3.2 (parse headers as C++ TUs): signalGain is DEFINED here (header-only,
// inline) and is NOT #included by any .cpp in the project. Without header parsing it is
// never captured; once headers are parsed as their own translation units it appears in
// model/functions.json. Caller-less on purpose, so it stays invisible (no interface row).
inline int signalGain(int sample) {
    return sample * 2;
}
