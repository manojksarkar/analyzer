#include "nested_class_tests.h"

int Outer::outerValue(int x) {
    Inner i;
    return i.innerValue(x) + x;
}

int Outer::Inner::innerValue(int x) {
    return x * 2;
}

int Outer::NestedStruct::getData() {
    return data;
}

void Container::PublicInner::f() {
}

void Container::PrivateInner::g() {
}
