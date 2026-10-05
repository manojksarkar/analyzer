#pragma once

// CoreStats — the second unit of component Sample Core: running totals and means.
//
// Dynamic Behaviour fixture. With the default filter (views.sequenceDiagrams.filterMode
// absent = skip_within_unit) a function gets a Dynamic Behaviour row only when it is
// called from ANOTHER COMPONENT and itself calls into ANOTHER UNIT of its own component.
// While Core was the component's only unit no Sample Core function could qualify, so a
// "Sample Core" document never had a Dynamic Behaviour section. CoreGateway is what Lib
// and Util call; this unit is what CoreGateway calls.

#define STATS_MAX_TOTAL 100000   // a running total saturates here instead of overflowing

PUBLIC int statsAccumulate(int total, int sample);   // adds one sample; negative samples are ignored
PUBLIC int statsAverage(int total, int count);       // integer mean; 0 when count is 0
