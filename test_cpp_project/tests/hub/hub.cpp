#include "hub.h"

#include "../../math/utils.h"
#include "../../outer/inner/helper.h"
#include "../enum/types.h"
#include "../structs/point_rect.h"

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

    return h + ps + e + static_cast<int>(st) + static_cast<int>(c);
}
