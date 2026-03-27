#include "visibility.h"

DB_TYPE g_dbType = 1;

PROTECTED DB_TYPE getDbTypeProtected() {
    return g_dbType;
}

PRIVATE DB_TYPE getDbTypePrivate() {
    return g_dbType;
}

PUBLIC void setDbTypePublic(DB_TYPE t) {
    g_dbType = t;
}
