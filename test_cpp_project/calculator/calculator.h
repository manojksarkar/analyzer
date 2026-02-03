#pragma once

int multiply(int a, int b);
int divide(int a, int b);

// Function-pointer-based API to exercise indirect calls
// The callback is expected to behave like: int f(int, int)
int applyWithCallback(int (*fn)(int, int), int a, int b);

// Simple virtual-function hierarchy to exercise polymorphic calls
class Operation {
public:
    virtual ~Operation() = default;
    virtual int apply(int a, int b) = 0;
};

class AddOperation : public Operation {
public:
    int apply(int a, int b) override;
};

class MultiplyOperation : public Operation {
public:
    int apply(int a, int b) override;
};

// Use a base-class pointer to dispatch virtually
int applyWithOperation(Operation* op, int a, int b);