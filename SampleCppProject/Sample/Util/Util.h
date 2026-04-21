#pragma once

// Shared utility module — called by both Core and Lib.
// Provides compute and scale helpers used across the Sample group.

PUBLIC extern int g_utilBase;     // baseline offset applied by utilCompute; direction In/Out

PUBLIC int utilCompute(int a, int b);      // called by Core and Lib -> fan-in behaviour diagram
PUBLIC int utilScale(int v, int factor);   // called by Core's hub function
PRIVATE int utilClip(int v, int lo, int hi); // private: excluded from interface table and behaviour diagram
