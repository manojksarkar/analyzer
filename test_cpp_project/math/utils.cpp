#include "utils.h"

PRIVATE int g_utilsCounter = 0;

PUBLIC int add(int a, int b) {
    ++g_utilsCounter;
    return a + b;
}

PUBLIC int subtract(int a, int b) {
    ++g_utilsCounter;
    return a - b;
}

PROTECTED int computeBoth(int a, int b) {
    return add(a, b) + subtract(a, b);
}
