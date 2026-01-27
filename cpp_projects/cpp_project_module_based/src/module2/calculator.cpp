#include "calculator.h"
#include "../module1/utils.h"

int multiply(int a, int b) {
    int result = 0;
    for (int i = 0; i < b; i++) {
        result = add(result, a);
    }
    return result;
}

int divide(int a, int b) {
    if (b == 0) return 0;
    return a / b;
}

