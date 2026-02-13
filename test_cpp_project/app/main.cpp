#include "../math/utils.h"
#include "../tests/param/types.h"
#include "../tests/ns/namespaces.h"
#include "../tests/nested/classes.h"
#include "../tests/poly/dispatch.h"
#include "../tests/enum/types.h"
#include "../tests/structs/point_rect.h"
#include "../tests/direction/read_write.h"
#include "../outer/inner/helper.h"

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
    (void)testUint8(1, 2);
    (void)testUint16(1, 2);
    (void)testUint32(1u, 2u);
    (void)testUint64(1u, 2u);
    (void)testInt8(1, 2);
    (void)testInt16(1, 2);
    (void)testInt32(1, 2);
    (void)testInt64(1, 2);
    (void)testMixedFixed(1u, 2, 3);
    (void)testUintptr(1u, 2u);
    (void)testIntptr(1, 2);
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

int runEnumTests() {
    Status s = getDefaultStatus();
    Color c = nextColor(getDefaultColor());
    Mode_t m = setMode(MODE_ACTIVE);
    (void)m;
    return static_cast<int>(s) + static_cast<int>(c);
}

int runTypeTests() {
    Point p = {1, 2};
    int sum = pointSum(p);
    getPointX(p);
    scalePoint(p, 2);
    Rect r = {{0, 0}, {10, 10}};
    int area = rectArea(&r);
    Data d;
    d.i = 42;
    int vi = getDataAsInt(d);
    noop();
    return sum + area + vi;
}

int runNestedFolderTests() {
    return nestedHelper(21);
}

int runDirectionTests() {
    int v = readGlobal();
    writeGlobal(10);
    int rw = readWriteGlobal(5);
    indirectWrite(20);
    return v + rw;
}

int main() {
    int result1 = calculate();
    int result2 = calculateWithCallback();
    int result3 = calculateWithPolymorphism();
    int result4 = runParamTypeTests();
    int result5 = runNamespaceTests();
    int result6 = runNestedClassTests();
    int result7 = runEnumTests();
    int result8 = runTypeTests();
    int result9 = runNestedFolderTests();
    int result10 = runDirectionTests();
    g_globalResult = result1 + result2 + result3 + result4 + result5 + result6 + result7 + result8 + result9 + result10;
    return g_globalResult;
}
