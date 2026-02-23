#pragma once

// Shared math utilities used by other test modules
int add(int a, int b);
int subtract(int a, int b);
int computeBoth(int a, int b);  // calls add + subtract (internal->internal for behaviour diagram)
