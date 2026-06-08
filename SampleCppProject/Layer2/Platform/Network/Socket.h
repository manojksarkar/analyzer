#ifndef SOCKET_H
#define SOCKET_H

int sock_open(int port);
void sock_close(int fd);
int sock_send(int fd, char *buf, int len);

#endif // SOCKET_H
