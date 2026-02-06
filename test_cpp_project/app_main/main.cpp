#include "../math_utils/utils.h"
#include "../param_tests/param_tests.h"
#include "../namespace_tests/namespace_tests.h"
#include "../nested_class_tests/nested_class_tests.h"
#include "../polymorphism_tests/polymorphism_tests.h"

int g_globalResult = 0;

int calculate() {
    int sum = add(10, 5);
    int product = multiply(sum, 3);
    return product;
}

int calculateWithCallback() {
    int viaAdd = applyWithCallback(&add, 2, 3);
    int viaSubtract = applyWithCallback(&subtract, 10, 4);
    return viaAdd + viaSubtract;
}

int runParamTypeTests() {
    int x = testIntParams(1, 2);
    unsigned int u = testUnsignedParams(1u, 2u);
    short s = testShortParams(1, 2);
    (void)testLongParams(1L, 2L);
    (void)testLongLongParams(1LL, 2LL);
    (void)testSizeTParams(1u, 2u);
    (void)testMixedParams(1, 2u, 3);
    int v = 0;
    (void)testPointerParams(&v);
    (void)testFunctionPtrParams(&add, 1, 2);
    return static_cast<int>(x + u + s);
}

int runNamespaceTests() {
    namespaceTestEntry();
    return 0;
}

int runNestedClassTests() {
    Outer o;
    Outer::Inner i;
    Outer::NestedStruct ns;
    ns.data = 42;
    return o.outerValue(1) + i.innerValue(2) + ns.getData();
}

int calculateWithPolymorphism() {
    AddOperation addOp;
    MultiplyOperation mulOp;
    Operation* base = &addOp;
    int v1 = applyWithOperation(base, 1, 2);
    base = &mulOp;
    int v2 = applyWithOperation(base, 3, 4);
    return v1 + v2;
}

int main() {
    int result1 = calculate();
    int result2 = calculateWithCallback();
    int result3 = calculateWithPolymorphism();
    int result4 = runParamTypeTests();
    int result5 = runNamespaceTests();
    int result6 = runNestedClassTests();
    g_globalResult = result1 + result2 + result3 + result4 + result5 + result6;
    return g_globalResult;
}
