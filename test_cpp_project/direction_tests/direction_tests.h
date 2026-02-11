#pragma once

// Test: direction inference - read-only global (In)
extern int g_readOnly;

// Test: write-only global (Out)
extern int g_writeOnly;

// Test: read+write global (In/Out)
extern int g_readWrite;

// Test: read global only -> function direction In
int readGlobal();

// Test: write global only -> function direction Out
void writeGlobal(int v);

// Test: read and write global -> function direction Out
int readWriteGlobal(int delta);

// Test: function calls Out function -> propagation to Out
void indirectWrite(int v);
