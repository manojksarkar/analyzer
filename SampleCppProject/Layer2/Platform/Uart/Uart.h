#ifndef UART_H
#define UART_H

void uart_init(int baud);
void uart_send(char c);
int uart_recv();

#endif // UART_H
