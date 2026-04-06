#pragma once

// =============================================================================
// Module  : app_services (poly portion)  |  Group: application
// Purpose : Polymorphism and callback edge cases — virtual dispatch, abstract
//           base classes, inheritance, and function-pointer callbacks.
// Edge cases covered:
//   - Free functions with basic arithmetic (multiply, divide) — PUBLIC
//   - Function pointer parameter: int (*fn)(int, int) — callback pattern
//     applyWithCallback passes any compatible free function at call site
//   - Abstract base class (Operation) with pure virtual int apply(a,b)
//   - Concrete subclasses (AddOperation, MultiplyOperation) with override
//   - Virtual destructor on base class
//   - Runtime polymorphic dispatch: applyWithOperation(Operation* op, ...)
//     — parser records virtual method calls; behaviour diagram shows dispatch arc
//   - Class methods parsed alongside free functions in the same unit
//   - Overridden methods captured in functions.json with correct qualifiedName
// =============================================================================

/// Simple multiply. Direction: In.
PUBLIC int multiply(int a, int b);

/// Simple divide. Direction: In.
PUBLIC int divide(int a, int b);

/// Applies any compatible function-pointer callback. Direction: In.
PUBLIC int applyWithCallback(int (*fn)(int, int), int a, int b);

/// Abstract operation interface — pure virtual dispatch target.
class Operation {
public:
    virtual ~Operation() = default;
    virtual int apply(int a, int b) = 0;
};

/// Concrete add operation — inherits Operation, overrides apply().
class AddOperation : public Operation {
public:
    int apply(int a, int b) override;
};

/// Concrete multiply operation — inherits Operation, overrides apply().
class MultiplyOperation : public Operation {
public:
    int apply(int a, int b) override;
};

/// Polymorphic dispatch entry-point — calls op->apply() at runtime. Direction: In.
PUBLIC int applyWithOperation(Operation* op, int a, int b);
