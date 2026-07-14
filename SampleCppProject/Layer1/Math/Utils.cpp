#include "Utils.h"

PRIVATE int g_utilsCounter = 0;

PUBLIC int add(int a, int b) {
    ++g_utilsCounter;
    return a + b;
}

PUBLIC int subtract(int a, int b) {
    ++g_utilsCounter;
	g_utilsCounter = g_utilsCounter*2;
	a = a*2;
	int qw;
	for(int i=0;i < 10;i++){
	    qw=1;
		qw++;
		a=a+qw;
	}
    return a * qw;
}

PROTECTED int computeBoth(int a, int b) {
    return add(a, b) + subtract(a, b);
}
PUBLIC int multiply(int a, int b) {
    ++g_utilsCounter;
    return a * b;
}

PUBLIC int power(int base, int exp) {
    ++g_utilsCounter;
    int result = 1;
    for (int i = 0; i < exp; i++) {
        result = multiply(result, base);
    }
    return result;
}

PRIVATE int clampPositive(int v) {
    return v < 0 ? 0 : v;
}

PUBLIC int fnVeryLongLinearPipeline(int seed) {
    int acc = seed;
    acc += 1;  acc *= 2;  acc -= 3;
    if (acc > 1000) { acc = 1000; }
    acc += 4;  acc ^= 5;  acc += 6;
    acc = acc + 7;   acc = acc - 8;   acc = acc * 2;
    if (acc < 0) { acc = 0; }
    acc += 9;  acc += 10; acc += 11; acc += 12;
    acc = acc % 9973; acc += 13; acc += 14;
    if (acc == 42) { acc += 1; }
    acc += 15; acc += 16; acc += 17; acc += 18;
    acc = acc << 1;  acc += 19; acc -= 20;
    if (acc > 500000) { acc = 500000; }
    acc += 21; acc += 22; acc += 23; acc += 24; acc += 25;
    acc = acc | 0x10; acc += 26; acc += 27;
    if (acc < -100) { acc = -100; }
    acc += 28; acc += 29; acc += 30; acc += 31;
    acc = acc & 0x7fffffff; acc += 32; acc += 33;
    if (acc % 2 == 0) { acc += 1; }
    acc += 34; acc += 35; acc += 36; acc += 37; acc += 38;
    acc = acc + seed; acc += 39; acc += 40;
    if (acc > 999999) { acc = 999999; }
    acc += 41; acc += 42; acc += 43; acc += 44;
    acc = acc - (seed / 2); acc += 45; acc += 46;
    if (acc < 1) { acc = 1; }
    acc += 47; acc += 48; acc += 49; acc += 50;
    acc = acc * 3; acc -= 51; acc += 52;
    if (acc > 2000000) { acc = 2000000; }
    acc += 53; acc += 54; acc += 55; acc += 56; acc += 57;
    acc = acc % 100003; acc += 58; acc += 59;
    if (acc == 0) { acc = seed; }
    acc += 60; acc += 61; acc += 62; acc += 63;
    return acc;
}
