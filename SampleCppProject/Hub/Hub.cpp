#include "Hub.h"

#include "Math/Utils.h"
#include "Outer/Inner/Helper.h"
#include "Types/Types.h"
#include "Types/PointRect.h"
#include "Sample/Core/Core.h"

PRIVATE static int hubValidate(int x) {
    return x >= 0 ? x : 0;
}

PUBLIC int hubCompute(int a, int b) {
    int va = hubValidate(a);
    int vb = hubValidate(b);
    int sum = add(va, vb);              // calls math/utils
    int diff = subtract(sum, vb);       // calls math/utils
    int h = helperCompute(diff);        // calls outer/helper
    int ps = pointSumWithAdd(a, b);     // calls tests/structs

    Status st = checkStatus(STATUS_OK); // calls tests/enum
    Color c = nextColor(getDefaultColor());
    int e = enumWithHelper(h);

    int ca = coreAdd(a, b);  // Hub -> Sample/Core (second external caller for coreAdd behaviour diagram)

    return h + ps + e + static_cast<int>(st) + static_cast<int>(c) + ca;
}
