#pragma once

typedef unsigned long long param_size_t;

// Test: signed int params -> range -2147483648-2147483647
int testIntParams(int a, int b);

// Test: unsigned int params -> range 0-0xFFFFFFFF
unsigned int testUnsignedParams(unsigned int a, unsigned int b);

// Test: short params -> range -32768-32767
short testShortParams(short a, short b);

// Test: long params -> range -2147483648-2147483647
long testLongParams(long a, long b);

// Test: long long params -> range -9223372036854775808-9223372036854775807
long long testLongLongParams(long long a, long long b);

// Test: size_t-like params -> range 0-0xFFFFFFFFFFFFFFFF
param_size_t testSizeTParams(param_size_t a, param_size_t b);

// Test: mixed param types
int testMixedParams(int a, unsigned int b, short c);

// Test: pointer param -> range NA
int testPointerParams(int* p);

// Test: function pointer param -> range NA
int testFunctionPtrParams(int (*fn)(int, int), int a, int b);
