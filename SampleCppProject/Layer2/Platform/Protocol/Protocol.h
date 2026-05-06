#ifndef PROTOCOL_H
#define PROTOCOL_H

void proto_init();
void proto_send(char *frame, int len);
int proto_recv(char *buf);

#endif // PROTOCOL_H
