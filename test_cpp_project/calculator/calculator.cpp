#include "calculator.h"
#include "../math_utils/utils.h"

// Global variable in module2
int g_calibrationFactor = 1;

int multiply(int a, int b) {
    int result = 0;
    for (int i = 0; i < b; i++) {
        result = add(result, a);
    }
    return result * g_calibrationFactor;
}

int divide(int a, int b) {
    if (b == 0) return 0;
    return a / b;
}

// Indirect call through a function pointer (cross-module: can point to add/subtract)
int applyWithCallback(int (*fn)(int, int), int a, int b) {
    return fn ? fn(a, b) : 0;
}

// Virtual-function implementations
int AddOperation::apply(int a, int b) {
    // Delegate to free function from another module
    return add(a, b);
}

int MultiplyOperation::apply(int a, int b) {
    // Delegate to multiply, which itself uses add in a loop
    return multiply(a, b);
}

// Use dynamic dispatch via base pointer
int applyWithOperation(Operation* op, int a, int b) {
    if (!op) return 0;
    return op->apply(a, b);
}
