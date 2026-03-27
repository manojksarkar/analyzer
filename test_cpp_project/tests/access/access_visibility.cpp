#include "access_visibility.h"

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
