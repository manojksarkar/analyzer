#ifndef OPSTABLE_H
#define OPSTABLE_H

#include "Types/Types.h"

/* Firmware-style registration table: the ops are reached ONLY through g_opsTable,
   never called by name. See OpsTable.cpp. */

typedef int (*OpsFn)(int, int);

PUBLIC int opsDispatch(int index, int a, int b);
PUBLIC int opsSeedValue(void);

#endif
