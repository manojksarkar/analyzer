#pragma once

// Test: direction inference - read-only global (In)
PUBLIC extern int g_readOnly;

// Test: write-only global (Out)
PRIVATE extern int g_writeOnly;

// Test: read+write global (In/Out)
PROTECTED extern int g_readWrite;

// Test: read global only -> function direction In
PUBLIC int readGlobal();

// Test: write global only -> function direction Out
PRIVATE void writeGlobal(int v);

// Test: read and write global -> function direction Out
PROTECTED int readWriteGlobal(int delta);

// Test: function calls Out function -> propagation to Out
PRIVATE void indirectWrite(int v);

// Cross-module: tests/direction -> math
PUBLIC int directionAdd(int a, int b);
