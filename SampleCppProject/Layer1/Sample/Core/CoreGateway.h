#pragma once

// CoreGateway — the entry points other components use to record samples in Sample Core.
//
// Dynamic Behaviour fixture (see CoreStats.h): each function here is called by exactly ONE
// function in another component and calls into CoreStats, so each gets exactly one Dynamic
// Behaviour row in the "Sample Core" document, under the default filter and under
// all_callers alike:
//
//     Lib - libRecordSample  ->  gatewayRecordSample  ->  statsAccumulate
//     Lib - libMeanOf        ->  gatewayMean          ->  statsAccumulate, statsAverage
//
// One caller each, and called directly: a caller of a caller would be traced as an external
// caller too, and those rows are where a diagram can end up beside another caller's name.

PUBLIC int gatewayRecordSample(int total, int sample);          // called from Lib
PUBLIC int gatewayMean(int total, int count, int lastSample);   // called from Lib
