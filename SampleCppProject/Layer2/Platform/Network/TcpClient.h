#ifndef TCPCLIENT_H
#define TCPCLIENT_H

int tcp_connect(int ip, int port);
void tcp_close(int fd);

#endif // TCPCLIENT_H
