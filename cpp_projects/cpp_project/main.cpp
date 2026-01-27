#include "math_utils.h"
#include "string_utils.h"

int calculate() {
    return multiply(2, 3);
}

int main() {
    int result = calculate();
    printMessage("Result calculated");
    return result;
}
