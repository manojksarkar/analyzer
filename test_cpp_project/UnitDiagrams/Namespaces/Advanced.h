#pragma once
// =============================================================================
// Module  : mw_advanced  |  Group: middleware
// Purpose : Advanced C++ patterns — namespaces, function overloading,
//           default parameters, const globals, private helpers inside namespace.
// Edge cases covered:
//   - C++ named namespace (Vehicle)
//   - Function overloading: clamp(v,max) vs clamp(v,min,max)
//   - Default parameter: scale(value, factor=1)
//   - Const global variables (MAX_SPEED, MIN_SPEED)
//   - PRIVATE function inside a namespace
//   - Cross-overload calls (2-arg overload delegates to 3-arg)
//   - Free functions alongside namespace-scoped functions
// =============================================================================

namespace Vehicle {
    extern const int MAX_SPEED;  ///< Upper bound for speed values (200)
    extern const int MIN_SPEED;  ///< Lower bound for speed values (0)

    /// Clamp value to [MIN_SPEED, max]. Delegates to the 3-arg overload.
    PUBLIC int clamp(int value, int max);

    /// Clamp value to [min, max].
    PUBLIC int clamp(int value, int min, int max);

    /// Scale value by factor (default factor = 1, demonstrating default param).
    PUBLIC int scale(int value, int factor = 1);

    /// Internal range validator — not part of the public interface.
    PRIVATE int _validate(int value);
}

/// Compute the span between two clamped values (cross-namespace free function).
PUBLIC int computeRange(int a, int b);

/// Linear interpolation between a and b at ratio t/100.
PROTECTED int lerp(int a, int b, int t);
