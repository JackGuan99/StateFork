CC = g++
CFLAGS = -std=c++17 -O2 -Wall
LDFLAGS = -pthread

TARGET = rdb
OBJS = rdb.o

$(TARGET):
$(OBJS):

PHONY += clean

clean:
	rm -f $(OBJS) $(TARGET) a.out

.PHONY: $(PHONY)