#include "utils.h"

int add(int a, int b) {
    return a + b;
}

int subtract(int a, int b) {
    return a - b;
}

// Namespace-based test functions to create more complex call patterns
namespace a {

void testA() {
    // Simple self-contained function, could call add/subtract if needed
    (void)add(1, 1);
}

void testB() {
    // Call another function in the same namespace
    testA();
}

} // namespace a

// Function that calls into the namespace using qualified names
void testC() {
    a::testB();
    a::testA();
}
