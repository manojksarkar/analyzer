#include "OpsTable.h"

/* A DIFFERENT unit that reaches opsAdd/opsSub through the table. Nothing here names
   them, so they have no caller edge — the units that READ the table are what makes
   Source/Destination meaningful, since the table itself usually sits in the same unit
   as the ops it publishes. */

extern const OpsFn g_opsTable[];

PUBLIC int opsClientApply(int index, int a, int b) {
    if (index < 0 || index > 1) return 0;
    return g_opsTable[index](a, b);
}
