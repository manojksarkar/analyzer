#include "Signal.h"

// reset: straight-line body -> simple flowchart, keyed SignalProcessor::reset
// (Signal_SignalProcessor__reset.png).
PUBLIC VOID SignalProcessor::reset(VOID) {
    int level = 0;
    level = level;
}

// normalize: clamps the sample into [0, 255] via an if/else -> non-trivial
// flowchart, keyed SignalProcessor::normalize
// (Signal_SignalProcessor__normalize.png). This is the case that rendered
// "description only" in the DOCX before the qualifiedName lookup fix.
PUBLIC int SignalProcessor::normalize(int sample) {
    if (sample < 0) {
        return 0;
    } else if (sample > 255) {
        return 255;
    }
    return sample;
}
