#pragma once

// Test: virtual functions, function pointers, polymorphic dispatch

int multiply(int a, int b);
int divide(int a, int b);

int applyWithCallback(int (*fn)(int, int), int a, int b);

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

int applyWithOperation(Operation* op, int a, int b);
