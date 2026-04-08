#pragma once

// Test: virtual functions, function pointers, polymorphic dispatch

PUBLIC int multiply(int a, int b);
PUBLIC int divide(int a, int b);

PUBLIC int applyWithCallback(int (*fn)(int, int), int a, int b);

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

PUBLIC int applyWithOperation(Operation* op, int a, int b);
