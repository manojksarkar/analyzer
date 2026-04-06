#pragma once

// Shared math utilities used by other test modules
PUBLIC int add(int a, int b);
PUBLIC int subtract(int a, int b);
PROTECTED int computeBoth(int a, int b);  // calls add + subtract (internal->internal for behaviour diagram)
