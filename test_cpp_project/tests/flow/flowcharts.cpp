#include "flowcharts.h"
#include "../../math/utils.h"

int fnIfSimple(int x) {
    if (x > 0) {
        return x + 1;
    }
    return x;
}

int fnIfElse(int x) {
    if (x > 0) {
        return 1;
    } else {
        return -1;
    }
}

int fnNestedIfElse(int a, int b) {
    if (a > 0) {
        if (b > 0) {
            return a + b;
        } else {
            return a - b;
        }
    } else {
        if (b > 0) {
            return b - a;
        } else {
            return -(a + b);
        }
    }
}

int fnIfElseIf(int x) {
    if (x < 0) {
        return -1;
    } else if (x == 0) {
        return 0;
    } else if (x < 10) {
        return 1;
    } else {
        return 10;
    }
}

int fnSwitchSimple(int op) {
    int result = 0;
    switch (op) {
        case 1: result = 10; break;
        case 2: result = 20; break;
        case 3: result = 30; break;
        default: result = 0; break;
    }
    return result;
}

int fnSwitchFallthrough(int tier) {
    int bonus = 0;
    switch (tier) {
        case 3: bonus += 100;
        case 2: bonus += 50;
        case 1: bonus += 10;
        default: bonus += 1; break;
    }
    return bonus;
}

int fnForLoop(int n) {
    int sum = 0;
    for (int i = 0; i < n; ++i) {
        sum += i;
    }
    return sum;
}

int fnForBreak(int n, int stop) {
    int sum = 0;
    for (int i = 0; i < n; ++i) {
        if (i == stop) break;
        sum += i;
    }
    return sum;
}

int fnForContinue(int n) {
    int sum = 0;
    for (int i = 0; i < n; ++i) {
        if (i % 2 == 0) continue;
        sum += i;
    }
    return sum;
}

int fnWhileLoop(int n) {
    int sum = 0;
    int i = 0;
    while (i < n) {
        sum += i;
        ++i;
    }
    return sum;
}

int fnDoWhile(int n) {
    int sum = 0;
    int i = 0;
    do {
        sum += i;
        ++i;
    } while (i < n);
    return sum;
}

int fnNestedFor(int rows, int cols) {
    int total = 0;
    for (int r = 0; r < rows; ++r) {
        for (int c = 0; c < cols; ++c) {
            total += r * cols + c;
        }
    }
    return total;
}

int fnForWithIf(int n) {
    int sum = 0;
    for (int i = 0; i < n; ++i) {
        if (i % 2 == 0) {
            sum += i * 2;
        } else {
            sum += i;
        }
    }
    return sum;
}

int fnWhileWithIf(int n) {
    int i = 0;
    int sum = 0;
    while (i < n) {
        if (i > n / 2) {
            sum += 1;
        } else {
            sum += 2;
        }
        ++i;
    }
    return sum;
}

int fnIfEarlyReturn(int x) {
    if (x < 0) return 0;
    if (x > 100) return 100;
    return x;
}

int fnSwitchReturn(int cmd) {
    switch (cmd) {
        case 1: return add(1, 2);
        case 2: return add(3, 4);
        case 3: return add(5, 6);
        default: return 0;
    }
}

int fnMixedForSwitch(int n) {
    int result = 0;
    for (int i = 0; i < n; ++i) {
        switch (i % 3) {
            case 0: result += 1; break;
            case 1: result += 2; break;
            case 2: result += 3; break;
        }
    }
    return result;
}

int fnMixedWhileIfElse(int n) {
    int i = 0;
    int out = 0;
    while (i < n) {
        if (i % 2 == 0) {
            out += 10;
        } else {
            out += 5;
        }
        ++i;
    }
    return out;
}

int fnDeeplyNested(int a, int b, int c) {
    if (a > 0) {
        if (b > 0) {
            if (c > 0) {
                return a + b + c;
            } else {
                return a + b;
            }
        } else {
            if (c > 0) {
                return a + c;
            } else {
                return a;
            }
        }
    } else {
        if (b > 0) {
            return b + c;
        } else {
            return c;
        }
    }
}

int fnMultipleReturns(int x, int y) {
    if (x < 0) return -1;
    if (y < 0) return -2;
    if (x == y) return 0;
    if (x > y) return 1;
    return 2;
}

int fnLoopNestedIfElse(int n) {
    int s = 0;
    for (int i = 0; i < n; ++i) {
        if (i < n / 3) {
            s += 1;
        } else if (i < 2 * n / 3) {
            s += 2;
        } else {
            s += 3;
        }
    }
    return s;
}

int runFlowTests() {
    int total = 0;
    total += fnIfSimple(5);
    total += fnIfElse(-3);
    total += fnNestedIfElse(2, 3);
    total += fnIfElseIf(5);
    total += fnSwitchSimple(2);
    total += fnSwitchFallthrough(2);
    total += fnForLoop(10);
    total += fnForBreak(20, 5);
    total += fnForContinue(10);
    total += fnWhileLoop(5);
    total += fnDoWhile(5);
    total += fnNestedFor(3, 4);
    total += fnForWithIf(8);
    total += fnWhileWithIf(6);
    total += fnIfEarlyReturn(50);
    total += fnSwitchReturn(2);
    total += fnMixedForSwitch(6);
    total += fnMixedWhileIfElse(4);
    total += fnDeeplyNested(1, 1, 1);
    total += fnMultipleReturns(3, 2);
    total += fnLoopNestedIfElse(9);
    return total;
}
