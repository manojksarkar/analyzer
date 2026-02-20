#include "../math/utils.h"
#include "../tests/param/types.h"
#include "../tests/ns/namespaces.h"
#include "../tests/nested/classes.h"
#include "../tests/poly/dispatch.h"
#include "../tests/enum/types.h"
#include "../tests/structs/point_rect.h"
#include "../tests/direction/read_write.h"
#include "../tests/hub/hub.h"
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

int runTypeTests() {
    Point p = {1, 2};
    int sum = pointSum(p);
    int cross = pointSumWithAdd(3, 4);  // tests/structs -> math
    getPointX(p);
    scalePoint(p, 2);
    Rect r = {{0, 0}, {10, 10}};
    int area = rectArea(&r);
    Data d;
    d.i = 42;
    int vi = getDataAsInt(d);
    noop();
    return sum + area + vi + cross;
}

int runNestedFolderTests() {
    int a = nestedHelper(21);
    int b = helperCompute(10);  // outer calls math
    int h = hubCompute(a, b);   // hub calls multiple units
    return a + b + h;
}

int runDirectionTests() {
    int v = readGlobal();
    writeGlobal(10);
    int rw = readWriteGlobal(5);
    indirectWrite(20);
    int da = directionAdd(1, 2);  // tests/direction -> math
    return v + rw + da;
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
