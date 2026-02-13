#pragma once

// Test: multiple namespaces, nested namespaces, qualified calls

namespace outer {
    void foo();
    void bar();
}

namespace outer::inner {
    void baz();
    void qux();
}

// Global function that calls into namespaces
void namespaceTestEntry();
