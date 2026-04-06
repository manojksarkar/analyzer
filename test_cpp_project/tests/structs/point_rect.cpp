#include "point_rect.h"
#include "../../math/utils.h"

// Test macros for unit header tables and defines pipeline
#define DEFAULT_SCALE_FACTOR 2
#define RECT_DEFAULT_WIDTH   10
#define RECT_DEFAULT_HEIGHT  20

PUBLIC int pointSumWithAdd(int a, int b) {
    return add(a, b);  // cross-module: tests/structs -> math
}

PUBLIC int pointSum(Point p) {
    return p.x + p.y;
}

PUBLIC int rectArea(const Rect* r) {
    if (!r) return 0;
    int w = r->bottomRight.x - r->topLeft.x;
    int h = r->bottomRight.y - r->topLeft.y;
    return w * h;
}

PUBLIC void scalePoint(Point& p, int factor) {
    p.x *= factor;
    p.y *= factor;
}

PROTECTED int getDataAsInt(Data d) {
    return d.i;
}

PRIVATE void noop() {
}

PUBLIC int getPointX(const Point& p) {
    return p.x;
}

PUBLIC void initWidget(Widget_t* w, int id, const char* name) {
    if (!w) return;
    w->id = id;
    w->name = name;
}

PROTECTED int areaOfSize(Size_t s) {
    return s.width * s.height;
}
