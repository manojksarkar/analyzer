#include "OpsTable.h"
#include "Math/Utils.h"

/* The reported defect: a function whose address sits in a registration table is a real
   entry point, but nothing CALLS it by name, so `_fn_is_private` (which equates "public"
   with "has a cross-file caller") used to bury it as private — dropping it from the
   interface table and from behaviour diagrams.

   Deliberately plain `static`, NOT annotated PRIVATE: an explicit PRIVATE annotation is
   authoritative and still wins over the address-taken rule.

   The table lives in the SAME file as the ops it publishes — the canonical firmware
   shape, and the reason the rule is by SHAPE (file-scope initializer) not by file. */

static int opsAdd(int a, int b) {
    return add(a, b);
}

static int opsSub(int a, int b) {
    return subtract(a, b);
}

/* Membership here is what makes opsAdd/opsSub public. No attempt is made to resolve
   which entry `g_opsTable[index]` reaches — that is statically unknowable. */
PUBLIC const OpsFn g_opsTable[] = { opsAdd, opsSub };

/* False-positive guard: this is a CALL in a file-scope initializer, not an address-take.
   opsSeed must stay private — if callee suppression ever stops propagating through
   clang's UNEXPOSED_EXPR wrapper, this is what catches it. */
static int opsSeed(void) {
    return 7;
}

PUBLIC int g_opsSeed = opsSeed();

PUBLIC int opsDispatch(int index, int a, int b) {
    if (index < 0 || index > 1) return 0;
    return g_opsTable[index](a, b);
}

PUBLIC int opsSeedValue(void) {
    return g_opsSeed;
}
