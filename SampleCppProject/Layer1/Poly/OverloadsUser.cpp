// OverloadsUser.cpp — another unit that calls every function of Overloads.cpp, so each of them
// is published and gets a section of its own.
#include "Overloads.h"

PUBLIC int ovlUseAll(int v) {
    OvlShape shape;
    OvlSquare square;
    int total = ovlScale(v) + ovlScale(v, 3) + (int)ovlScale(1.5f);
    total += fastpath::ovlInit(v) + slowpath::ovlInit(v);
    total += shape.area(v) + square.area(v);
    total += shape.resize(v) + shape.resize(v, 2);
    return total + ovlAlone(v);
}
