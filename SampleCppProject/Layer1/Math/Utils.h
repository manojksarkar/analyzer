#pragma once

// Shared math utilities used by other test modules
PUBLIC int add(int a, int b);
PUBLIC int subtract(int a, int b);
PUBLIC int power(int base, int exp);  // base raised to exp (exp >= 0)
PROTECTED int computeBoth(int a, int b);  // calls add + subtract (internal->internal for behaviour diagram)
PUBLIC int fnVeryLongLinearPipeline(int seed);  // long linear CFG — forces tall flowchart PNG to slice into parts
