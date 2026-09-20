#include "ClassStatics.h"
#include "StatDefs.h"

// The out-of-line definitions. Clang reports storage_class NONE on these and STATIC on the
// in-class declarations, which is why the recorded cursor is chosen by is_definition().
int StatCounters::s_publicCount = 0;
int StatCounters::s_protectedMark = 0;
int StatCounters::s_privateSecret = 0;
int StatRegistry::s_entries = 0;
StatCounts StatCounters::s_counts = {0, 0};
XY::AB NsCounters::var = {0, 0};
XY::AB NS::Wrapped::var = {0, 0};

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

// ---------------------------------------------------------------------------------------
// Writes that reach the static member through a FIELD. `statInsertCache` is the shape a
// cache insert has in real firmware: void, named for what it does rather than Set/Get, and
// its only effect is a bump of one counter inside a shared struct. Nothing else in the
// sample covers it -- every other static-member test here names the member directly.
// ---------------------------------------------------------------------------------------

// Postfix bump of a field of a static member -> In.
// Two things have to hold at once for this: `x++` must register as a WRITE (the operator is
// the LAST token, not the first), and that write must be carried through `.inserts` down to
// `s_counts`. Either one missing records a read, and the direction comes out Out.
PUBLIC void statInsertCache(void) {
    StatCounters::s_counts.inserts++;
}

// Plain assignment to a field -> In, and a pure write: the field is set, never consulted.
PUBLIC void statPrimeCache(void) {
    StatCounters::s_counts.hits = 0;
}

// Compound assignment to a field -> In, and the member is in BOTH sets: `+=` reads the old
// value before storing the new one. Writing wins the direction; the read still has to be
// recorded, because the SWE.4 precondition has to set the member up first.
PUBLIC void statAddCacheHits(void) {
    StatCounters::s_counts.hits += 2;
}

// Reads a field and writes none -> Out. The mirror of statInsertCache: same member, same
// field access, opposite direction, so a walker that simply logged every member access as a
// write would pass the three above and fail here.
PUBLIC void statReadCacheHits(void) {
    int seen = StatCounters::s_counts.hits;
    (void)seen;
}

// Non-void return: direction is settled by the return value before globals are reached.
PUBLIC int statReadLimit(void) {
    return StatCounters::s_limit;
}

// A member reaching its own class's PROTECTED static, class-qualified, through a field.
void NsCounters::bumpNs(void) {
    NsCounters::var.member++;
}

void NsCounters::peekNs(void) {
    int seen = NsCounters::var.member;
    (void)seen;
}

// Unqualified -- the form a member normally uses.
void NsCounters::bumpNsPlain(void) {
    var.member++;
}

// Namespace-qualified, because the class itself is nested in a namespace.
void NS::Wrapped::bumpWrapped(void) {
    NS::Wrapped::var.member++;
}
