#ifndef I2C_H
#define I2C_H

void i2c_init();
void i2c_write(int addr, int data);
int i2c_read(int addr);

#endif // I2C_H
