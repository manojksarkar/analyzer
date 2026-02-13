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

// Test: union
union Data {
    int i;
    float f;
    char c;
};

// Test: struct as parameter (by value)
int pointSum(Point p);

// Test: struct as parameter (by pointer)
int rectArea(const Rect* r);

// Test: struct by reference
void scalePoint(Point& p, int factor);

// Test: union as parameter
int getDataAsInt(Data d);

// Test: void return
void noop();

// Test: const reference parameter
int getPointX(const Point& p);
