#include "utils.h"

int g_utilsCounter = 0;

int add(int a, int b) {
    ++g_utilsCounter;
    return a + b;
}

int subtract(int a, int b) {
    ++g_utilsCounter;
    return a - b;
}

int computeBoth(int a, int b) {
    return add(a, b) + subtract(a, b);
}
