#pragma once

// Test: struct with multiple fields
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
