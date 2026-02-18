#include "helper.h"
#include "../../math/utils.h"

int nestedHelper(int x) {
    return x * 2;
}

int helperCompute(int x) {
    return add(x, 1);  // cross-module: outer -> math
}
