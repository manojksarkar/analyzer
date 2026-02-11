#pragma once

// Fixed-width types (avoid dependency on cstdint for parsing)
typedef unsigned char param_uint8_t;
typedef unsigned short param_uint16_t;
typedef unsigned int param_uint32_t;
typedef unsigned long long param_uint64_t;
typedef signed char param_int8_t;
typedef short param_int16_t;
typedef int param_int32_t;
typedef long long param_int64_t;
typedef unsigned long long param_uintptr_t;
typedef long long param_intptr_t;

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

// Test: fixed-width unsigned (param_* to avoid cstdint)
param_uint8_t testUint8(param_uint8_t a, param_uint8_t b);
param_uint16_t testUint16(param_uint16_t a, param_uint16_t b);
param_uint32_t testUint32(param_uint32_t a, param_uint32_t b);
param_uint64_t testUint64(param_uint64_t a, param_uint64_t b);

// Test: fixed-width signed
param_int8_t testInt8(param_int8_t a, param_int8_t b);
param_int16_t testInt16(param_int16_t a, param_int16_t b);
param_int32_t testInt32(param_int32_t a, param_int32_t b);
param_int64_t testInt64(param_int64_t a, param_int64_t b);

// Test: mixed fixed-width
param_uint32_t testMixedFixed(param_uint32_t a, param_int64_t b, param_uint8_t c);

// Test: pointer-sized integers
param_uintptr_t testUintptr(param_uintptr_t a, param_uintptr_t b);
param_intptr_t testIntptr(param_intptr_t a, param_intptr_t b);
