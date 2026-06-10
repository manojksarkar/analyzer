#include "Hub.h"

#include "Math/Utils.h"
#include "Outer/Inner/Helper.h"
#include "Types/Types.h"
#include "Types/PointRect.h"
#include "Sample/Core/Core.h"
#include "Sample/Lib/Lib.h"
#include "Sample/Util/Util.h"

PRIVATE static int hubValidate(int x) {
    return x >= 0 ? x : 0;
}

PUBLIC int hubCompute(int a, int b) {
    int va = hubValidate(a);
    int vb = hubValidate(b);
    int sum = add(va, vb);
    int diff = subtract(sum, vb);
    int h = helperCompute(diff);
    int ps = pointSumWithAdd(a, b);

    Status st = checkStatus(STATUS_OK);
    Color c = nextColor(getDefaultColor());
    int e = enumWithHelper(h);

    // Sample/Core — Hub is the second external caller alongside App
    int ca  = coreAdd(a, b);
    int cp  = coreProcess(a, b);
    int co  = coreOrchestrate(a, b);
    int cpl = corePipeline(a);
    int cnb = coreNestedBranch(a, b);
    int cwc = coreWhileCount(5);
    int cer = coreEarlyReturn(a);

    // Sample/Lib — Hub is the second external caller alongside App
    int la = libAdd(a, b);
    int lm = libMultiply(a, b);
    int ln = libNormalize(a, 100);
    int ll = libLinearScale(a, 100, 200);

    // Sample/Util — Hub is the second external caller alongside App
    int ua = utilAbs(a);
    int uc = utilChain(a);
    int ub = utilBlend(a, b, 40);

    int total = h + ps + e + static_cast<int>(st) + static_cast<int>(c)
              + ca + cp + co + cpl + cnb + cwc + cer
              + la + lm + ln + ll
              + ua + uc + ub;
    return total;
}
