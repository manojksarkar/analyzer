#include "ClassStatics.h"
#include "StatDefs.h"

// The out-of-line definitions. Clang reports storage_class NONE on these and STATIC on the
// in-class declarations, which is why the recorded cursor is chosen by is_definition().
int StatCounters::s_publicCount = 0;
int StatCounters::s_protectedMark = 0;
int StatCounters::s_privateSecret = 0;
int StatRegistry::s_entries = 0;

// Writes a static member -> direction In.
PUBLIC void statBumpPublic(void) {
    StatCounters::s_publicCount++;
}

// Reads one and writes none -> direction Out, with the member named in the reason.
PUBLIC void statReadPublic(void) {
    int seen = StatCounters::s_publicCount;
    (void)seen;
}

// Writes a PRIVATE static member -> still In; the member stays out of the interface table.
PUBLIC void statBumpPrivate(void) {
    StatCounters::s_privateSecret++;
}

// Writes one only through a callee -> In, via the transitive write set.
PUBLIC void statBumpIndirect(void) {
    statBumpPublic();
}

// Writes the member whose class is declared in a differently named header.
PUBLIC void statBumpRegistry(void) {
    StatRegistry::s_entries++;
}

// Non-void return: direction is settled by the return value before globals are reached.
PUBLIC int statReadLimit(void) {
    return StatCounters::s_limit;
}
