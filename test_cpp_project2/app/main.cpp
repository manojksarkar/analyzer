#include "../math/utils.h"

int calculate() {
    int sum = add(10, 5);
    int product = multiply(sum, 3);
    return product;
}

int compute() {
    int a = subtract(20, 8);
    int b = add(a, 2);
    return multiply(b, 2);
}

int process() {
    int x = add(1, 2);
    int y = subtract(10, 3);
    return add(x, y);
}

int run() {
    int v = multiply(3, 4);
    return add(v, subtract(5, 1));
}

int main() {
    int r1 = calculate();
    int r2 = compute();
    int r3 = process();
    int r4 = run();
    return r1 + r2 + r3 + r4;
}
