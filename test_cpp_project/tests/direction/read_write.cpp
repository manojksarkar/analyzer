#include "read_write.h"
#include "../../math/utils.h"

int g_readOnly = 42;   // read-only: never written
int g_writeOnly = 0;   // write-only: only written
int g_readWrite = 0;   // both read and written

int readGlobal() {
    return g_readOnly;
}

void writeGlobal(int v) {
    g_writeOnly = v;
}

int readWriteGlobal(int delta) {
    g_readWrite += delta;
    return g_readWrite;
}

void indirectWrite(int v) {
    writeGlobal(v);
}

int directionAdd(int a, int b) {
    return add(a, b);  // cross-module: tests/direction -> math
}
