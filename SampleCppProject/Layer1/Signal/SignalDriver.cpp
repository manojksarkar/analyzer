#include "Signal.h"
#include "SignalDriver.h"

// Separate translation unit that consumes SignalProcessor. This gives
// SignalProcessor::reset / SignalProcessor::normalize a CROSS-FILE caller, so the
// model deriver keeps them public (visible) instead of marking them private —
// see engine/model_deriver.py::_has_external_caller. Without an external caller
// the methods are hidden, never become unit interfaces, and the flowchart
// section (the thing this fixture demonstrates) never renders in the DOCX.
PUBLIC int acquireAndNormalize(int raw) {
    SignalProcessor sp;
    sp.reset();
    return sp.normalize(raw);
}
