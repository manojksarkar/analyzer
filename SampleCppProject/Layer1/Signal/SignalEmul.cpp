#include "Signal.h"

// Fixture for 3.1 (exclude emulator files): the basename contains "emul", so the parser
// skips this whole translation unit by default (is_project_file -> _EXCLUDE_NAME_PATTERNS).
// emulReset must therefore NOT appear in model/functions.json on a normal run, but DOES
// appear when the parse is invoked with --include-emulator.
PUBLIC int emulReset(int channel) {
    int state = channel;
    if (state < 0) {
        state = 0;
    }
    return state;
}
