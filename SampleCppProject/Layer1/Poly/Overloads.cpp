// Overloads.cpp — see Overloads.h. Every body is different on purpose: a section that shows
// another overload's flowchart or test steps is then visibly wrong.
#include "Overloads.h"

PUBLIC int ovlScale(int value) {
    if (value < 0) {
        return 0;
    }
    return value * 2;
}

PUBLIC int ovlScale(int value, int factor) {
    if (factor == 0) {
        return value;
    }
    return value * factor;
}

PUBLIC float ovlScale(float value) {
    return value * 0.5f;
}

namespace fastpath {
PUBLIC int ovlInit(int seed) {
    return seed + 1;
}
}

namespace slowpath {
PUBLIC int ovlInit(int seed) {
    if (seed > 10) {
        return 10;
    }
    return seed;
}
}

int OvlShape::area(int side) {
    return side;
}

int OvlShape::resize(int side) {
    return area(side);
}

int OvlShape::resize(int width, int height) {
    if (width > height) {
        return width;
    }
    return height;
}

int OvlSquare::area(int side) {
    return side * side;
}

PUBLIC int ovlAlone(int value) {
    return value;
}
