#include "../module2/calculator.h"
#include "../module1/utils.h"

int calculate() {
    int sum = add(10, 5);
    int product = multiply(sum, 3);
    return product;
}

int main() {
    int result = calculate();
    return result;
}

