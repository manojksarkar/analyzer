#pragma once

// Test: named enum with explicit values
enum Status {
    STATUS_OK = 0,
    STATUS_ERR = -1,
    STATUS_PENDING = 1
};

// Test: named enum with implicit values
enum Color {
    RED,
    GREEN,
    BLUE
};

// Test: typedef enum
typedef enum {
    MODE_IDLE = 0,
    MODE_ACTIVE = 1,
    MODE_DONE = 2
} Mode_t;

// Test: enum as parameter
Status checkStatus(Status s);
Color nextColor(Color c);
Mode_t setMode(Mode_t m);

// Test: enum return
Status getDefaultStatus();
Color getDefaultColor();

// Cross-module: tests/enum -> outer
int enumWithHelper(int x);
