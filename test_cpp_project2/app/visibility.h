#pragma once

#define PRIVATE
#define PROTECTED
#define PUBLIC

typedef int DB_TYPE;

PROTECTED DB_TYPE getDbTypeProtected();
PRIVATE DB_TYPE getDbTypePrivate();
PUBLIC void setDbTypePublic(DB_TYPE t);
