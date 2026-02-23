#include "../math/utils.h"
#include "../tests/flow/flowcharts.h"
#include "../tests/poly/dispatch.h"
#include "../tests/enum/types.h"
#include "../tests/structs/point_rect.h"
#include "../tests/direction/read_write.h"
#include "../tests/hub/hub.h"
#include "../outer/inner/helper.h"

int g_globalResult = 0;

int calculate() {
    int sum = add(10, 5);
    int both = computeBoth(3, 4);  // math: external->computeBoth->add,subtract (internal)
    int product = multiply(sum + both, 3);
    return product;
}

int calculateWithCallback() {
    int viaAdd = applyWithCallback(&add, 2, 3);
    int viaSubtract = applyWithCallback(&subtract, 10, 4);
    return viaAdd + viaSubtract;
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
    int h = enumWithHelper(7);  // tests/enum -> outer
    (void)m;
    return static_cast<int>(s) + static_cast<int>(c) + h;
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
    int result4 = runEnumTests();
    int result5 = runTypeTests();
    int result6 = runNestedFolderTests();
    int result7 = runDirectionTests();
    int result8 = runFlowTests();
    g_globalResult = result1 + result2 + result3 + result4 + result5 + result6 + result7 + result8;
    return g_globalResult;
}
