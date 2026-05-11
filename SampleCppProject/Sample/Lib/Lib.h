#pragma once

// Lib — arithmetic helpers called by Core; some call Util (fan-in).

PUBLIC int libAdd(int a, int b);
PUBLIC int libSubtract(int a, int b);
PUBLIC int libMultiply(int a, int b);
PUBLIC int libAbs(int v);
PUBLIC int libMax(int a, int b);
PUBLIC int libMin(int a, int b);
PUBLIC int libNormalize(int v, int max);
PUBLIC int libLinearScale(int v, int from_max, int to_max);   // normalize then rescale

PRIVATE int libClamp(int v, int lo, int hi);   // private range guard
PRIVATE int libSign(int v);                    // -1 / 0 / +1
PRIVATE int libBound(int v, int max);          // calls libClamp
