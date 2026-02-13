#include "namespaces.h"
#include "../../math/utils.h"

namespace outer {

void foo() {
    (void)add(1, 2);
}

void bar() {
    foo();
}

} // namespace outer

namespace outer::inner {

void baz() {
    outer::foo();
}

void qux() {
    baz();
}

} // namespace outer::inner

void namespaceTestEntry() {
    outer::foo();
    outer::bar();
    outer::inner::baz();
    outer::inner::qux();
}
