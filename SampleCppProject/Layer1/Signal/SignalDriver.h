#pragma once

// Declares SignalDriver's public entry so a unit in ANOTHER COMPONENT (Cross|Hub)
// can call it. Two things follow, and both are the point of this fixture:
//   - acquireAndNormalize gains a caller, so model_deriver keeps it PUBLIC instead
//     of hiding it (see _has_external_caller);
//   - that caller sits in a different component, so it is an EXTERNAL caller.
// Its body already reaches SignalProcessor in the sibling unit Signal, so the
// forward call chain spans TWO units of one component -- the shape the behaviour
// diagram selector requires (SkipWithinUnitDiagramSelector: public + external
// caller + >1 in-component unit). Before this header the whole fixture produced
// zero behaviour diagrams, and so zero Dynamic Behaviour test specs; see
// docs/spec/SWE4_WIKI.md, "Dynamic Behaviour test specs".
// SignalDriver.h and SignalDriver.cpp share a path, so they remain ONE unit.
PUBLIC int acquireAndNormalize(int raw);
