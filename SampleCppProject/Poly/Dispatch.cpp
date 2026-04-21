#include "Dispatch.h"
#include "Math/Utils.h"
#include "Hub/Hub.h"

PROTECTED int g_polymorphismFactor = 1;

PRIVATE static int multiplyCore(int a, int b) {
    int result = 0;
    for (int i = 0; i < b; i++) {
        result = add(result, a);
    }
    return result;
}

PUBLIC int multiply(int a, int b) {
    int prod = multiplyCore(a, b);
    int h = hubCompute(a, b);
    return (prod + (h % 7)) * g_polymorphismFactor;
}

PUBLIC int divide(int a, int b) {
    if (b == 0) return 0;
    return a / b;
}

PUBLIC int applyWithCallback(int (*fn)(int, int), int a, int b) {
    return fn ? fn(a, b) : 0;
}

PUBLIC int AddOperation::apply(int a, int b) {
    return add(a, b);
}

PUBLIC int MultiplyOperation::apply(int a, int b) {
    return multiply(a, b);
}

PUBLIC int applyWithOperation(Operation* op, int a, int b) {
    if (!op) return 0;
    return op->apply(a, b);
}
