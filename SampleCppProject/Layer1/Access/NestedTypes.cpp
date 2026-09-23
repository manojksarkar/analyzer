#include "NestedTypes.h"

int NestedOwner::s_publicCount = 0;
int NestedOwner::s_protectedMark = 0;
int NestedOwner::s_privateSecret = 0;

// A file-scope `static`: internal linkage, so NO other unit can reach it. It is recorded
// as public all the same -- visibility never looks at storage class -- so it earns an
// interface row like any file-scope global. Open question in SWE3_WIKI N.1.5.
static int s_fileLocal = 0;

// A file-scope struct in the same unit, for the plain struct/class row. It reaches the
// unit header table in its own right now, not only through a `typedef struct {…} S;`.
struct NestedStats {
    int applied;
    int rejected;
};

static NestedStats s_stats = { 0, 0 };

// Uses the file-scope union and alias, so neither is dead code.
static NestedWord s_word = { 0 };

int NestedOwner::nestedApply(int v) {
    NestedAlias_t small = (NestedAlias_t)(v & 0xFFFF);
    PrivateWord pw = { 0 };
    PrivateAlias_t pb = (PrivateAlias_t)(v & 0xFF);
    s_word.whole += small + pw.whole + pb;
    PrivateState st = (v > 0) ? NS_BUSY : NS_IDLE;
    PrivateByte_t b = (PrivateByte_t)(v & 0xFF);
    PrivateSlot slot = { v };

    s_privateSecret += slot.id;
    s_publicCount++;
    s_fileLocal += b;

    if (st == NS_BUSY) {
        s_stats.applied++;
        return s_publicCount;
    }
    s_stats.rejected++;
    return s_fileLocal;
}

int NestedOwner::nestedPublicMode(PublicMode m) {
    PublicKey_t key = (m == NM_FAST) ? 1 : 2;
    PublicSlot slot = { key, 1 };
    ProtectedFlag f = (slot.used != 0) ? NF_SET : NF_NONE;
    s_protectedMark += (f == NF_SET) ? 1 : 0;
    return slot.id + s_protectedMark;
}
