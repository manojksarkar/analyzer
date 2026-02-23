#include "dispatch.h"
#include "../../math/utils.h"
#include "../hub/hub.h"

int g_polymorphismFactor = 1;

static int multiplyCore(int a, int b) {
    int result = 0;
    for (int i = 0; i < b; i++) {
        result = add(result, a);
    }
    return result;
}

int multiply(int a, int b) {
    int prod = multiplyCore(a, b);
    int h = hubCompute(a, b);
    return (prod + (h % 7)) * g_polymorphismFactor;
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
