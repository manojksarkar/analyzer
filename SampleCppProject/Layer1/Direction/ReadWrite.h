#pragma once

// Test: direction inference - read-only global
PUBLIC extern int g_readOnly;

// Test: write-only global
PRIVATE extern int g_writeOnly;

// Test: read+write global
PROTECTED extern int g_readWrite;

// Test: a global DEFINED in this header (not extern) -> exercises header-defined-global
// capture + write tracking (3.4). A function that writes it must get direction In.
PRIVATE static int g_hdrGlobal = 0;

// Test: reads a global only -> function direction Out
PUBLIC int readGlobal();

// Test: writes a global only -> function direction In
PRIVATE void writeGlobal(int v);

// Test: reads and writes a global -> function direction In
PROTECTED int readWriteGlobal(int delta);

// Test: calls a writer -> writes a global TRANSITIVELY -> direction In (3.4)
PRIVATE void indirectWrite(int v);

// Test: writes the HEADER-defined global directly -> direction In (3.4 header-global case)
PUBLIC void setHdrGlobal(int v);

// Test: writes the header-defined global TRANSITIVELY (via setHdrGlobal) -> direction In (3.4)
PUBLIC void setHdrGlobalIndirect(int v);

// Cross-module: tests/direction -> math
PUBLIC int directionAdd(int a, int b);
