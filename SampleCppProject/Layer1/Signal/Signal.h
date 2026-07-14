#pragma once

// Repro for the namespaced-flowchart-in-DOCX fix (task 3.7):
// class SignalProcessor is DECLARED here, but its methods are DEFINED in another
// translation unit (Signal.cpp) as SignalProcessor::reset / SignalProcessor::normalize.
// The flowchart producer keys these by qualifiedName ("SignalProcessor::normalize",
// PNG Signal_SignalProcessor__normalize.png), so the DOCX exporter must look them up
// by qualifiedName too — otherwise only the description printed and the flowchart
// image was dropped. VOID is supplied by the analyzer via -DVOID=void.
#define PUBLIC

class SignalProcessor {
public:
    PUBLIC VOID reset(VOID);
    PUBLIC int normalize(int sample);
};
