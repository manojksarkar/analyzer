#include "Advanced.h"

// =============================================================================
// Module  : mw_advanced  |  Group: middleware
// Demonstrates:
//   - Namespace-scoped const globals
//   - Function overloading (clamp with 2 and 3 parameters)
//   - Default parameters (scale)
//   - Private namespace helper (_validate)
//   - Overload delegation: 2-arg clamp calls 3-arg clamp
//   - Free functions using namespace members (computeRange, lerp)
// =============================================================================

namespace Vehicle {

PUBLIC const int MAX_SPEED = 200;
PUBLIC const int MIN_SPEED = 0;

PRIVATE int _validate(int value) {
    if (value < MIN_SPEED) return MIN_SPEED;
    if (value > MAX_SPEED) return MAX_SPEED;
    return value;
}

PUBLIC int clamp(int value, int max) {
    // Overload delegation: 2-arg delegates to 3-arg overload
    return clamp(value, MIN_SPEED, max);
}

PUBLIC int clamp(int value, int min, int max) {
    if (value < min) return min;
    if (value > max) return max;
    return value;
}

PUBLIC int scale(int value, int factor) {
    // Uses private helper; factor defaults to 1 at call site
    return _validate(value) * factor;
}

} // namespace Vehicle

PUBLIC int computeRange(int a, int b) {
    // Cross-namespace free function calling namespace overloads
    int lo = Vehicle::clamp(a, Vehicle::MIN_SPEED, Vehicle::MAX_SPEED);
    int hi = Vehicle::clamp(b, Vehicle::MIN_SPEED, Vehicle::MAX_SPEED);
    return hi - lo;
}

PROTECTED int lerp(int a, int b, int t) {
    // Linear interpolation: t is a percentage (0–100)
    return a + (b - a) * t / 100;
}
