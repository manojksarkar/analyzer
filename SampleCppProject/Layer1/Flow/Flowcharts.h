#pragma once

// Test: object reached through an accessor call — exercises the fn()->field
// label shapes (the call supplies the object; the statement does the work).
typedef struct {
    int timeSlot;    // scheduling time slot for the unit
    int retryCount;  // remaining retry attempts
    int active;      // non-zero while the slot is in use
} FlowSlot_t;

PUBLIC int runFlowTests();
