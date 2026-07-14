#pragma once

// Util — shared utility module; called by both Core and Lib (fan-in target).

PUBLIC extern int g_utilBase;   // baseline offset applied by utilCompute -> direction Out (reads only)

PUBLIC int utilCompute(int a, int b);         // called by Core and Lib -> fan-in behaviour diagram
PUBLIC int utilScale(int v, int factor);      // called by Core's hub function
PUBLIC int utilAbs(int v);                    // if/else flowchart pattern
PUBLIC int utilClamp(int v, int lo, int hi);  // calls utilClip
PUBLIC int utilNorm(int v, int max);          // calls utilCompute + utilClip
PUBLIC int utilBlend(int a, int b, int w);    // weighted blend; calls utilClamp
PUBLIC int utilLoopAccum(int n);              // for loop accumulator
PUBLIC int utilChain(int v);                  // chain: utilAbs -> utilNorm -> utilScale

PRIVATE int utilClip(int v, int lo, int hi);  // raw clamp — private
PRIVATE int utilDouble(int v);                // doubles value; private helper used in chain
PRIVATE int utilHalve(int v);                 // halves value; private helper
