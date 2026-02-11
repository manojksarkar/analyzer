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

param_uint8_t testUint8(param_uint8_t a, param_uint8_t b) {
    return static_cast<param_uint8_t>(a + b);
}

param_uint16_t testUint16(param_uint16_t a, param_uint16_t b) {
    return static_cast<param_uint16_t>(a + b);
}

param_uint32_t testUint32(param_uint32_t a, param_uint32_t b) {
    return a + b;
}

param_uint64_t testUint64(param_uint64_t a, param_uint64_t b) {
    return a + b;
}

param_int8_t testInt8(param_int8_t a, param_int8_t b) {
    return static_cast<param_int8_t>(a + b);
}

param_int16_t testInt16(param_int16_t a, param_int16_t b) {
    return static_cast<param_int16_t>(a + b);
}

param_int32_t testInt32(param_int32_t a, param_int32_t b) {
    return a + b;
}

param_int64_t testInt64(param_int64_t a, param_int64_t b) {
    return a + b;
}

param_uint32_t testMixedFixed(param_uint32_t a, param_int64_t b, param_uint8_t c) {
    return static_cast<param_uint32_t>(a + static_cast<param_uint32_t>(b) + c);
}

param_uintptr_t testUintptr(param_uintptr_t a, param_uintptr_t b) {
    return a + b;
}

param_intptr_t testIntptr(param_intptr_t a, param_intptr_t b) {
    return a + b;
}
