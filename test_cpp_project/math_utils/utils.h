#pragma once

int add(int a, int b);
int subtract(int a, int b);

// Simple namespace-based test functions to exercise analyzer
namespace a {
    void testA();
    void testB();
}

// Function that calls into the namespace with qualified calls
void testC();