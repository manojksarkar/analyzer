#include "AccessVisibility.h"

DB_TYPE g_selectedDbType = DB_MAIN;
int g_dbVersion = 7;

PROTECTED DB_TYPE _MTM_SB_GETDbType() {
    return g_selectedDbType;
}

PRIVATE int _MTM_SB_GETDbVersion() {
    return g_dbVersion;
}

PUBLIC void _MTM_SB_SETDbType(DB_TYPE t) {
    g_selectedDbType = t;
}

int DbSession::open(int slot) {
    return slot + backoffMs() + secretKey();
}

int DbSession::retryBudget() {
    return g_dbVersion;
}
