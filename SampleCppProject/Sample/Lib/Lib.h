#pragma once

// Cross-module target for Sample/Core behaviour diagram arcs.

PUBLIC int libAdd(int a, int b);
PUBLIC int libNormalize(int v, int max);
PRIVATE int libClamp(int v, int max);   // private: excluded from interface table and behaviour diagram
