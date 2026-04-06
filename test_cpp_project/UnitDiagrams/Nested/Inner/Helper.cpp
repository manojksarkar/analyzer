#include "Helper.h"
#include "../../BasicMath/Utils.h"

PROTECTED int nestedHelper(int x) {
    return x * 2;
}

PUBLIC int helperCompute(int x) {
    return add(x, 1);  // cross-module: outer -> math
}
