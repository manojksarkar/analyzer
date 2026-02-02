#include "../module2/calculator.h"
#include "../module1/utils.h"

int calculate() {
    int sum = add(10, 5);
    int product = multiply(sum, 3);
    return product;
}

// Exercise function-pointer based calls across modules
int calculateWithCallback() {
    // Call add via function pointer
    int viaAdd = applyWithCallback(&add, 2, 3);
    // Call subtract via function pointer
    int viaSubtract = applyWithCallback(&subtract, 10, 4);
    return viaAdd + viaSubtract;
}

// Exercise polymorphic calls via virtual functions
int calculateWithPolymorphism() {
    AddOperation addOp;
    MultiplyOperation mulOp;

    // Dispatch through base pointer
    Operation* base = &addOp;
    int v1 = applyWithOperation(base, 1, 2);

    base = &mulOp;
    int v2 = applyWithOperation(base, 3, 4);

    return v1 + v2;
}

int main() {
    int result1 = calculate();
    int result2 = calculateWithCallback();
    int result3 = calculateWithPolymorphism();
    return result1 + result2 + result3;
}
