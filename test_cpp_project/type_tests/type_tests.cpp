#include "type_tests.h"

int pointSum(Point p) {
    return p.x + p.y;
}

int rectArea(const Rect* r) {
    if (!r) return 0;
    int w = r->bottomRight.x - r->topLeft.x;
    int h = r->bottomRight.y - r->topLeft.y;
    return w * h;
}

void scalePoint(Point& p, int factor) {
    p.x *= factor;
    p.y *= factor;
}

int getDataAsInt(Data d) {
    return d.i;
}

void noop() {
}

int getPointX(const Point& p) {
    return p.x;
}
