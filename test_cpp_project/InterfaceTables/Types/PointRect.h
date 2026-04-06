#pragma once

// =============================================================================
// Module  : mw_types (structs portion)  |  Group: middleware
// Purpose : Type-system edge cases — struct and union varieties used as
//           parameters and return types.
// Edge cases covered:
//   - Named struct with multiple primitive fields (Point: int x, int y)
//   - Nested struct: Rect contains two Point instances
//   - Typedef struct — anonymous struct with typedef alias (Widget_t, Size_t)
//   - Union with overlapping int/float/char fields (Data)
//   - Struct passed by value (pointSum)
//   - Struct passed by const pointer (rectArea)
//   - Struct passed by reference with mutation (scalePoint — direction: In/Out)
//   - Union passed by value (getDataAsInt)
//   - Void return (noop — PRIVATE, excluded from interface table)
//   - Const reference parameter (getPointX)
//   - Cross-module call into hal_math (pointSumWithAdd -> math::add)
//   - PUBLIC / PROTECTED / PRIVATE visibility mix
// =============================================================================

// Named struct with multiple primitive fields
struct Point {
    int x;
    int y;
};

// Test: struct with nested struct
struct Rect {
    Point topLeft;
    Point bottomRight;
};

// Test: typedef struct
typedef struct {
    int id;
    const char* name;
} Widget_t;

// Test: another typedef struct (for RAG/unit-header coverage)
typedef struct {
    int width;
    int height;
} Size_t;

// Test: typedef struct usage
PUBLIC void initWidget(Widget_t* w, int id, const char* name);
PROTECTED int areaOfSize(Size_t s);

// Test: union
union Data {
    int i;
    float f;
    char c;
};

// Test: struct as parameter (by value)
PUBLIC int pointSum(Point p);

// Test: struct as parameter (by pointer)
PUBLIC int rectArea(const Rect* r);

// Test: struct by reference
PUBLIC void scalePoint(Point& p, int factor);

// Test: union as parameter
PROTECTED int getDataAsInt(Data d);

// Test: void return
PRIVATE void noop();

// Test: const reference parameter
PUBLIC int getPointX(const Point& p);

// Cross-module: tests/structs -> math
PUBLIC int pointSumWithAdd(int a, int b);
