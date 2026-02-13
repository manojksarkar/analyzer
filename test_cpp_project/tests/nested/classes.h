#pragma once

// Test: nested classes, nested structs, inner class methods

class Outer {
public:
    class Inner {
    public:
        int innerValue(int x);
    };
    struct NestedStruct {
        int data;
        int getData();
    };
    int outerValue(int x);
};

class Container {
public:
    class PublicInner {
    public:
        void f();
    };
private:
    class PrivateInner {
    public:
        void g();
    };
};
