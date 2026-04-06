#pragma once

// =============================================================================
// Module  : mw_types (enum portion)  |  Group: middleware
// Purpose : Type-system edge cases — enum varieties used as parameters and
//           return types.
// Edge cases covered:
//   - Named enum with explicit integer values (Status: OK=0, ERR=-1, PENDING=1)
//   - Named enum with implicit sequential values (Color: RED=0, GREEN=1, BLUE=2)
//   - Typedef enum with explicit values (Mode_t) — anonymous enum + typedef alias
//   - Enum as function parameter (pass-by-value)
//   - Enum as function return type
//   - All three visibility macros: PUBLIC, PROTECTED, PRIVATE on enum-using fns
//   - Cross-module call: enumWithHelper -> outer/inner (tests inter-group arc)
// =============================================================================

// Named enum with explicit values
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
PUBLIC Status checkStatus(Status s);
PUBLIC Color nextColor(Color c);
PROTECTED Mode_t setMode(Mode_t m);

// Test: enum return
PUBLIC Status getDefaultStatus();
PUBLIC Color getDefaultColor();

// Cross-module: tests/enum -> outer
PRIVATE int enumWithHelper(int x);
