#include "ReadWrite.h"
#include "Math/Utils.h"

PUBLIC int g_readOnly = 42;    // read-only: never written
PRIVATE int g_writeOnly = 0;   // write-only: only written
PROTECTED int g_readWrite = 0; // both read and written

PUBLIC int readGlobal() {
    return g_readOnly;
}

PRIVATE void writeGlobal(int v) {
    g_writeOnly = v;
}

PROTECTED int readWriteGlobal(int delta) {
    g_readWrite += delta;
    return g_readWrite;
}

PRIVATE void indirectWrite(int v) {
    writeGlobal(v);
}

PUBLIC void setHdrGlobal(int v) {
    g_hdrGlobal = v;      // writes a HEADER-defined global -> direction In
}

PUBLIC void setHdrGlobalIndirect(int v) {
    setHdrGlobal(v);      // transitive write of a header-defined global -> direction In
}

PUBLIC int directionAdd(int a, int b) {
    return add(a, b);  // cross-module: tests/direction -> math
}
