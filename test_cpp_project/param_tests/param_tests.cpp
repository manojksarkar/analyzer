#include "param_tests.h"

int testIntParams(int a, int b) {
    return a + b;
}

unsigned int testUnsignedParams(unsigned int a, unsigned int b) {
    return a + b;
}

short testShortParams(short a, short b) {
    return static_cast<short>(a + b);
}

long testLongParams(long a, long b) {
    return a + b;
}

long long testLongLongParams(long long a, long long b) {
    return a + b;
}

param_size_t testSizeTParams(param_size_t a, param_size_t b) {
    return a + b;
}

int testMixedParams(int a, unsigned int b, short c) {
    return static_cast<int>(a + b + c);
}

int testPointerParams(int* p) {
    return p ? *p : 0;
}

int testFunctionPtrParams(int (*fn)(int, int), int a, int b) {
    return fn ? fn(a, b) : 0;
}
