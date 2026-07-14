#ifndef LOGBUF_H
#define LOGBUF_H

void log_buf_push(const char *s);
const char *log_buf_pop();

#endif // LOGBUF_H
