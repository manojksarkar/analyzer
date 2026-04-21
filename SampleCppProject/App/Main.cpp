#include "Math/Utils.h"
#include "Flow/Flowcharts.h"
#include "Poly/Dispatch.h"
#include "Types/Types.h"
#include "Types/PointRect.h"
#include "Direction/ReadWrite.h"
#include "Hub/Hub.h"
#include "Outer/Inner/Helper.h"
#include "Sample/Core/Core.h"
#include "Sample/Lib/Lib.h"
#include "Sample/Util/Util.h"

PUBLIC int g_globalResult = 0;

PUBLIC int calculate() {
    int sum = add(10, 5);
    int both = computeBoth(3, 4);  // math: external->computeBoth->add,subtract (internal)
    int product = multiply(sum + both, 3);
    return product;
}

PUBLIC int calculateWithCallback() {
    int viaAdd = applyWithCallback(&add, 2, 3);
    int viaSubtract = applyWithCallback(&subtract, 10, 4);
    return viaAdd + viaSubtract;
}

PUBLIC int calculateWithPolymorphism() {
    AddOperation addOp;
    MultiplyOperation mulOp;
    Operation* base = &addOp;
    int v1 = applyWithOperation(base, 1, 2);
    base = &mulOp;
    int v2 = applyWithOperation(base, 3, 4);
    return v1 + v2;
}

PRIVATE int runEnumTests() {
    Status s = getDefaultStatus();
    Color c = nextColor(getDefaultColor());
    Mode_t m = setMode(MODE_ACTIVE);
    int h = enumWithHelper(7);  // tests/enum -> outer
    (void)m;
    return static_cast<int>(s) + static_cast<int>(c) + h;
}

PRIVATE int runTypeTests() {
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

PRIVATE int runNestedFolderTests() {
    int a = nestedHelper(21);
    int b = helperCompute(10);  // outer calls math
    int h = hubCompute(a, b);   // hub calls multiple units
    return a + b + h;
}

PRIVATE int runDirectionTests() {
    int v = readGlobal();
    writeGlobal(10);
    int rw = readWriteGlobal(5);
    indirectWrite(20);
    int da = directionAdd(1, 2);  // tests/direction -> math
    return v + rw + da;
}

PRIVATE int runSampleTests() {
    // Core calls — App is external caller for Sample/Core behaviour diagrams
    int a = coreAdd(3, 4);
    int b = coreProcess(10, 100);
    int c = coreOrchestrate(a, b);
    int d = corePipeline(a);
    int e = coreNestedBranch(a, b);
    int f = coreWhileCount(10);
    int g = coreEarlyReturn(50);
    int h = coreDoWhileClamp(500, 200);
    int ii = coreMultiCallChain(a, b, 3);

    // Lib calls — App is external caller for Sample/Lib behaviour diagrams
    int la = libAdd(1, 2);
    int lm = libMultiply(3, 4);
    int labs = libAbs(-7);
    int lmax = libMax(la, lm);
    int lls = libLinearScale(50, 100, 200);

    // Util calls — App is external caller for Sample/Util behaviour diagrams
    int ua = utilAbs(-5);
    int uc = utilChain(ua);
    int ub = utilBlend(10, 90, 30);
    int ul = utilLoopAccum(5);

    coreSetResult(a + b + c + d + e + f + g + h + ii + la + lm + labs + lmax + lls + ua + uc + ub + ul);
    return coreGetCount();
}

PUBLIC int main() {
    int result1 = calculate();
    int result2 = calculateWithCallback();
    int result3 = calculateWithPolymorphism();
    int result4 = runEnumTests();
    int result5 = runTypeTests();
    int result6 = runNestedFolderTests();
    int result7 = runDirectionTests();
    int result8 = runFlowTests();
    int result9 = runSampleTests();
    g_globalResult = result1 + result2 + result3 + result4 + result5 + result6 + result7 + result8 + result9;
    return g_globalResult;
}
