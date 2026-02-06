#include "polymorphism_tests.h"
#include "../math_utils/utils.h"

int g_polymorphismFactor = 1;

int multiply(int a, int b) {
    int result = 0;
    for (int i = 0; i < b; i++) {
        result = add(result, a);
    }
    return result * g_polymorphismFactor;
}

int divide(int a, int b) {
    if (b == 0) return 0;
    return a / b;
}

int applyWithCallback(int (*fn)(int, int), int a, int b) {
    return fn ? fn(a, b) : 0;
}

int AddOperation::apply(int a, int b) {
    return add(a, b);
}

int MultiplyOperation::apply(int a, int b) {
    return multiply(a, b);
}

int applyWithOperation(Operation* op, int a, int b) {
    if (!op) return 0;
    return op->apply(a, b);
}
